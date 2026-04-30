"""
Attendance Service
- Handles punch-in / punch-out logic
- Creates/updates daily attendance records
- Validates punch rules (duplicates, sequence, rate limits)
"""
import json
import logging
from datetime import datetime, date, timedelta, time
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.staff import Staff
from app.models.attendance import AttendancePunch, AttendanceRecord, AttendanceStatus
from app.models.audit import AuditLog
from app.services.ot_service import calculate_work_hours, determine_status, is_weekly_off
from app.config import settings

logger = logging.getLogger(__name__)


def get_today() -> date:
    """Get current date (for testability)."""
    return datetime.now().date()


def get_now() -> datetime:
    """Get current datetime."""
    return datetime.now()


def get_last_punch(db: Session, staff_id: int, today: date) -> Optional[AttendancePunch]:
    """Get the last valid punch for a staff member today."""
    return db.query(AttendancePunch).filter(
        AttendancePunch.staff_id == staff_id,
        AttendancePunch.is_valid == True,
        func.date(AttendancePunch.punch_time) == today,
    ).order_by(AttendancePunch.punch_time.desc()).first()


def count_recent_punches(db: Session, staff_id: int) -> int:
    """Count punches in the last hour (rate limiting)."""
    one_hour_ago = get_now() - timedelta(hours=1)
    return db.query(AttendancePunch).filter(
        AttendancePunch.staff_id == staff_id,
        AttendancePunch.punch_time >= one_hour_ago,
    ).count()


def determine_punch_type(db: Session, staff_id: int, today: date) -> str:
    """
    Auto-determine punch type based on last punch.
    First punch of the day = IN, alternates after.
    """
    last_punch = get_last_punch(db, staff_id, today)
    if last_punch is None:
        return "IN"
    return "OUT" if last_punch.punch_type == "IN" else "IN"


def record_punch(
    db: Session,
    staff_id: int,
    confidence: float,
    device_info: str = ""
) -> Tuple[bool, str, Optional[dict]]:
    """
    Record a punch for a staff member.

    Validation rules:
    1. Rate limit: max N punches per hour
    2. Auto punch type: IN/OUT alternation
    3. Create/update daily attendance record
    4. Calculate hours on punch-out

    Returns: (success, message, punch_data)
    """
    now = get_now()
    today = now.date()

    # Get staff info
    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        return False, "Staff not found", None

    if not staff.is_active:
        return False, "Staff is deactivated", None

    # Rate limit check
    recent_count = count_recent_punches(db, staff_id)
    if recent_count >= settings.MAX_PUNCH_ATTEMPTS_PER_HOUR:
        log_failed_attempt(db, staff_id, "Rate limit exceeded", confidence)
        return False, f"Too many punch attempts ({recent_count} in last hour). Please wait.", None

    # Check existing punches for today (1 IN + 1 OUT only)
    today_punches = db.query(AttendancePunch).filter(
        AttendancePunch.staff_id == staff_id,
        AttendancePunch.is_valid == True,
        func.date(AttendancePunch.punch_time) == today,
    ).all()
    
    has_punch_in = any(p.punch_type == "IN" for p in today_punches)
    has_punch_out = any(p.punch_type == "OUT" for p in today_punches)
    
    # Determine punch type and validate
    if not has_punch_in:
        punch_type = "IN"
    elif has_punch_in and not has_punch_out:
        punch_type = "OUT"
    else:
        # Already has both IN and OUT
        return False, "You have already punched IN and OUT today. Only 1 punch-in and 1 punch-out allowed per day.", None

    # Create punch record
    punch = AttendancePunch(
        staff_id=staff_id,
        punch_type=punch_type,
        punch_time=now,
        confidence=confidence,
        is_valid=True,
        device_info=device_info,
    )
    db.add(punch)

    # Update or create daily attendance record
    record = db.query(AttendanceRecord).filter(
        AttendanceRecord.staff_id == staff_id,
        AttendanceRecord.date == today,
    ).first()

    if punch_type == "IN":
        if record is None:
            record = AttendanceRecord(
                staff_id=staff_id,
                date=today,
                punch_in_time=now,
                status="Partial",  # Will be updated on punch-out
            )
            db.add(record)
        else:
            # Second IN (after a completed IN-OUT pair) - update
            record.punch_in_time = now
            record.punch_out_time = None
            record.status = "Partial"
    else:  # OUT
        if record is None:
            # Punch-out without punch-in — anomaly
            record = AttendanceRecord(
                staff_id=staff_id,
                date=today,
                punch_out_time=now,
                status="Invalid",
            )
            db.add(record)
            db.commit()
            log_audit(db, "PUNCH_OUT_NO_IN", "attendance", punch.id, details={
                "staff_id": staff_id, "employee_id": staff.employee_id
            })
            return True, f"Punch OUT recorded (Warning: No Punch IN found today)", {
                "employee_id": staff.employee_id,
                "name": staff.name,
                "punch_type": "OUT",
                "punch_time": now.isoformat(),
                "confidence": confidence,
                "warning": "No punch-in recorded today"
            }

        record.punch_out_time = now

        # Calculate hours
        if record.punch_in_time:
            on_weekly_off = is_weekly_off(today, staff.weekly_off)
            hours = calculate_work_hours(
                record.punch_in_time,
                now,
                shift_start_str=staff.shift_start,
                shift_end_str=staff.shift_end,
                is_weekly_off_day=on_weekly_off,
            )
            record.total_work_minutes = hours["total_work_minutes"]
            record.regular_minutes = hours["regular_minutes"]
            record.ot_minutes = hours["ot_minutes"]
            record.status = determine_status(
                record.punch_in_time,
                now,
                is_weekly_off=on_weekly_off,
                regular_minutes=hours["regular_minutes"],
                shift_start_str=staff.shift_start,
                shift_end_str=staff.shift_end,
            )

    db.commit()

    # Audit log
    log_audit(db, f"PUNCH_{punch_type}", "attendance", punch.id, details={
        "staff_id": staff_id,
        "employee_id": staff.employee_id,
        "confidence": confidence,
    })

    return True, f"Punch {punch_type} recorded successfully", {
        "employee_id": staff.employee_id,
        "name": staff.name,
        "punch_type": punch_type,
        "punch_time": now.isoformat(),
        "confidence": confidence,
    }


def log_failed_attempt(db: Session, staff_id: int, reason: str, confidence: float):
    """Log a rejected punch attempt."""
    punch = AttendancePunch(
        staff_id=staff_id,
        punch_type="REJECTED",
        punch_time=get_now(),
        confidence=confidence,
        is_valid=False,
        rejection_reason=reason,
    )
    db.add(punch)
    db.commit()


def log_audit(db: Session, action: str, entity_type: str, entity_id: int,
              performed_by: str = "system", details: dict = None):
    """Create an immutable audit log entry."""
    audit = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        performed_by=performed_by,
        details=json.dumps(details) if details else None,
    )
    db.add(audit)
    db.commit()


def edit_attendance_record(
    db: Session,
    record_id: int,
    punch_in_str: Optional[str],
    punch_out_str: Optional[str],
    status: Optional[str],
    edit_reason: str,
    editor: str,
) -> Tuple[bool, str]:
    """
    Admin edit of an attendance record.
    Stores original values, logs edit.
    """
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        return False, "Record not found"

    staff = db.query(Staff).filter(Staff.id == record.staff_id).first()
    original = {
        "punch_in": record.punch_in_time.isoformat() if record.punch_in_time else None,
        "punch_out": record.punch_out_time.isoformat() if record.punch_out_time else None,
        "status": record.status,
    }

    # Store originals (only first edit preserves original)
    if not record.is_edited:
        record.original_punch_in = record.punch_in_time
        record.original_punch_out = record.punch_out_time

    if punch_in_str:
        h, m = punch_in_str.split(":")
        record.punch_in_time = datetime.combine(record.date, __import__("datetime").time(int(h), int(m)))

    if punch_out_str:
        h, m = punch_out_str.split(":")
        record.punch_out_time = datetime.combine(record.date, __import__("datetime").time(int(h), int(m)))

    if status:
        record.status = status

    # Recalculate hours if both punches exist
    if record.punch_in_time and record.punch_out_time:
        on_weekly_off = is_weekly_off(record.date, staff.weekly_off) if staff else False
        hours = calculate_work_hours(
            record.punch_in_time,
            record.punch_out_time,
            shift_start_str=staff.shift_start if staff else None,
            shift_end_str=staff.shift_end if staff else None,
            is_weekly_off_day=on_weekly_off,
        )
        record.total_work_minutes = hours["total_work_minutes"]
        record.regular_minutes = hours["regular_minutes"]
        record.ot_minutes = hours["ot_minutes"]

    record.is_edited = True
    record.edited_by = editor
    record.edited_at = get_now()
    record.edit_reason = edit_reason

    db.commit()

    # Audit
    log_audit(db, "EDIT_ATTENDANCE", "attendance", record.id, performed_by=editor, details={
        "original": original,
        "edited": {
            "punch_in": record.punch_in_time.isoformat() if record.punch_in_time else None,
            "punch_out": record.punch_out_time.isoformat() if record.punch_out_time else None,
            "status": record.status,
        },
        "reason": edit_reason,
    })

    return True, "Record updated successfully"


def status_to_initial(status: str) -> str:
    """Convert status string to a short 1-2 character code for the matrix view."""
    map = {
        "Present": "P",
        "Absent": "A",
        "Partial": "PL",
        "Invalid": "I",
        "Weekly Off": "WO"
    }
    return map.get(status, "-")


def get_muster_matrix(
    db: Session,
    year: int,
    month: int,
    employee_id: Optional[str] = None,
    name: Optional[str] = None,
    designation: Optional[str] = None,
    location: Optional[str] = None,
) -> dict:
    """
    Get monthly attendance in matrix format (Traditional Muster Book).
    Supports filtering by employee_id, name (partial), and designation (partial).
    """
    from calendar import monthrange
    _, last_day = monthrange(year, month)
    days = list(range(1, last_day + 1))
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    # All active staff (or staff who had records in this period)
    query = db.query(Staff).filter(Staff.is_active == True)
    if employee_id:
        query = query.filter(Staff.employee_id == employee_id)
    if name:
        query = query.filter(Staff.name.ilike(f"%{name}%"))
    if designation:
        query = query.filter(Staff.designation.ilike(f"%{designation}%"))
    if location:
        query = query.filter(Staff.location.ilike(f"%{location}%"))
    all_staff = query.order_by(Staff.employee_id).all()
    
    # All records for the month
    records = db.query(AttendanceRecord).filter(
        AttendanceRecord.date >= start_date,
        AttendanceRecord.date <= end_date
    ).all()

    # Organize records by staff_id and day
    record_map = {} # {staff_id: {day: status}}
    for r in records:
        if r.staff_id not in record_map:
            record_map[r.staff_id] = {}
        record_map[r.staff_id][r.date.day] = status_to_initial(r.status)

    staff_data = []
    for s in all_staff:
        row = {
            "employee_id": s.employee_id,
            "name": s.name,
            "days": {},
            "summary": {"P": 0, "A": 0, "PL": 0, "WO": 0, "I": 0, "Total OT": 0}
        }
        
        staff_records = record_map.get(s.id, {})
        for day in days:
            current_date = date(year, month, day)
            status = staff_records.get(day)
            
            if status is None:
                # Check for future vs past for unrecorded days
                if current_date > date.today():
                    status = "-"
                elif is_weekly_off(current_date, s.weekly_off):
                    status = "WO"
                else:
                    status = "A"
            
            row["days"][day] = status
            if status in row["summary"]:
                row["summary"][status] += 1

        # Calculate OT summary for the month
        ot_minutes = db.query(func.sum(AttendanceRecord.ot_minutes)).filter(
            AttendanceRecord.staff_id == s.id,
            AttendanceRecord.date >= start_date,
            AttendanceRecord.date <= end_date
        ).scalar() or 0
        row["summary"]["Total OT"] = f"{ot_minutes // 60}h {ot_minutes % 60}m"
        
        staff_data.append(row)

    return {
        "days": days,
        "staff_data": staff_data
    }


def get_muster_book(
    db: Session,
    year: int,
    month: int,
    employee_id: Optional[str] = None,
    name: Optional[str] = None,
    designation: Optional[str] = None,
    location: Optional[str] = None,
) -> List[dict]:
    """
    Get monthly muster book data.
    Returns list of daily records for all or specified staff.
    If employee_id is provided, returns entries for EVERY day of the month.
    """
    from calendar import monthrange
    _, last_day = monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    # 1. If searching for a specific individual, we want to show ALL days of the month
    if employee_id and not (name or designation or location):
        staff = db.query(Staff).filter(Staff.employee_id == employee_id).first()
        if not staff:
            return []
            
        # Get existing records
        records = db.query(AttendanceRecord).filter(
            AttendanceRecord.staff_id == staff.id,
            AttendanceRecord.date >= start_date,
            AttendanceRecord.date <= end_date
        ).all()
        
        record_map = {r.date: r for r in records}
        
        results = []
        for day in range(1, last_day + 1):
            curr_date = date(year, month, day)
            rec = record_map.get(curr_date)
            
            if rec:
                results.append({
                    "id": rec.id,
                    "employee_id": staff.employee_id,
                    "name": staff.name,
                    "designation": staff.designation,
                    "date": rec.date.isoformat(),
                    "punch_in": rec.punch_in_time.strftime("%I:%M %p") if rec.punch_in_time else "-",
                    "punch_out": rec.punch_out_time.strftime("%I:%M %p") if rec.punch_out_time else "-",
                    "total_hours": f"{rec.total_work_minutes // 60}h {rec.total_work_minutes % 60}m",
                    "regular_hours": f"{rec.regular_minutes // 60}h {rec.regular_minutes % 60}m",
                    "ot_hours": f"{rec.ot_minutes // 60}h {rec.ot_minutes % 60}m",
                    "ot_minutes": rec.ot_minutes,
                    "status": rec.status,
                    "is_edited": rec.is_edited,
                })
            else:
                # Determine status for missing day
                if curr_date > date.today():
                    status = "-"
                elif is_weekly_off(curr_date, staff.weekly_off):
                    status = "Weekly Off"
                else:
                    status = "Absent"
                    
                results.append({
                    "id": None,
                    "employee_id": staff.employee_id,
                    "name": staff.name,
                    "designation": staff.designation,
                    "date": curr_date.isoformat(),
                    "punch_in": "-",
                    "punch_out": "-",
                    "total_hours": "0h 0m",
                    "regular_hours": "0h 0m",
                    "ot_hours": "0h 0m",
                    "ot_minutes": 0,
                    "status": status,
                    "is_edited": False,
                })
        return results

    # 2. General search - return only actual records
    query = db.query(AttendanceRecord, Staff).join(
        Staff, AttendanceRecord.staff_id == Staff.id
    ).filter(
        AttendanceRecord.date >= start_date,
        AttendanceRecord.date <= end_date,
    )

    if employee_id:
        query = query.filter(Staff.employee_id == employee_id)
    if name:
        query = query.filter(Staff.name.ilike(f"%{name}%"))
    if designation:
        query = query.filter(Staff.designation.ilike(f"%{designation}%"))
    if location:
        query = query.filter(Staff.location.ilike(f"%{location}%"))

    query = query.order_by(Staff.employee_id, AttendanceRecord.date)
    records = query.all()

    return [
        {
            "id": rec.id,
            "employee_id": s.employee_id,
            "name": s.name,
            "designation": s.designation,
            "date": rec.date.isoformat(),
            "punch_in": rec.punch_in_time.strftime("%I:%M %p") if rec.punch_in_time else "-",
            "punch_out": rec.punch_out_time.strftime("%I:%M %p") if rec.punch_out_time else "-",
            "total_hours": f"{rec.total_work_minutes // 60}h {rec.total_work_minutes % 60}m",
            "regular_hours": f"{rec.regular_minutes // 60}h {rec.regular_minutes % 60}m",
            "ot_hours": f"{rec.ot_minutes // 60}h {rec.ot_minutes % 60}m",
            "ot_minutes": rec.ot_minutes,
            "status": rec.status,
            "is_edited": rec.is_edited,
        }
        for rec, s in records
    ]

def manual_mark_attendance(
    db: Session,
    employee_id: str,
    punch_in_str: Optional[str],
    punch_out_str: Optional[str],
    status: str,
    reason: str,
    editor: str,
    target_date: Optional[date] = None,
) -> Tuple[bool, str]:
    """Manually mark attendance for a staff member for a given date (defaults to today)."""
    staff = db.query(Staff).filter(Staff.employee_id == employee_id).first()
    if not staff:
        return False, "Staff not found"

    mark_date = target_date or date.today()
    record = db.query(AttendanceRecord).filter(
        AttendanceRecord.staff_id == staff.id,
        AttendanceRecord.date == mark_date,
    ).first()

    if record is None:
        record = AttendanceRecord(staff_id=staff.id, date=mark_date)
        db.add(record)

    if punch_in_str and punch_in_str.strip():
        h, m = punch_in_str.split(":")
        record.punch_in_time = datetime.combine(mark_date, time(int(h), int(m)))
    
    if punch_out_str and punch_out_str.strip():
        h, m = punch_out_str.split(":")
        record.punch_out_time = datetime.combine(mark_date, time(int(h), int(m)))

    record.status = status
    record.is_edited = True
    record.edited_by = editor
    record.edited_at = datetime.utcnow()
    record.edit_reason = f"[Manual Mark] {reason}"

    # Calculate hours
    if record.punch_in_time and record.punch_out_time:
        on_weekly_off = is_weekly_off(mark_date, staff.weekly_off)
        hours = calculate_work_hours(
            record.punch_in_time,
            record.punch_out_time,
            shift_start_str=staff.shift_start,
            shift_end_str=staff.shift_end,
            is_weekly_off_day=on_weekly_off,
        )
        record.total_work_minutes = hours["total_work_minutes"]
        record.regular_minutes = hours["regular_minutes"]
        record.ot_minutes = hours["ot_minutes"]

    db.commit()
    
    # Log audit
    log_audit(db, "MANUAL_MARK", "attendance", record.id, performed_by=editor, details={
        "employee_id": employee_id,
        "date": str(mark_date),
        "status": status,
        "reason": reason
    })
    
    return True, "Attendance marked successfully"


def bulk_manual_mark_attendance(
    db: Session,
    employee_ids: list,
    target_date: date,
    punch_in_str: Optional[str],
    punch_out_str: Optional[str],
    status: str,
    reason: str,
    editor: str,
) -> dict:
    """Mark attendance for multiple staff members at once. Returns summary."""
    success = 0
    failed = 0
    errors = []

    for emp_id in employee_ids:
        ok, msg = manual_mark_attendance(
            db, emp_id, punch_in_str, punch_out_str,
            status, reason, editor, target_date=target_date,
        )
        if ok:
            success += 1
        else:
            failed += 1
            errors.append(f"{emp_id}: {msg}")

    return {"success": success, "failed": failed, "errors": errors}
