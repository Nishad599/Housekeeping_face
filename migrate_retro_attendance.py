import sys
import logging
from datetime import date
from sqlalchemy.orm import Session

# Needs to be run from the root of the project
try:
    from app.database import SessionLocal
    from app.models.attendance import AttendanceRecord
    from app.models.staff import Staff
    from app.services.ot_service import calculate_work_hours, determine_status, is_weekly_off
except ImportError:
    print("Error: Must run Script from the face-attendance project root.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

def run_migration():
    """
    Recalculate ALL attendance records using current OT rounding & weekly-off rules.
    
    This ensures:
      1. Sunday (weekly-off) records are marked "Weekly Off" (not "Present"),
         with regular_minutes=0 and only OT counted.
      2. OT is rounded to the nearest whole hour (e.g. 2h40m → 3h, 3h15m → 3h).
    """
    db: Session = SessionLocal()
    
    try:
        # Get ALL records that have both punch in and out
        records = db.query(AttendanceRecord).filter(
            AttendanceRecord.punch_in_time.isnot(None),
            AttendanceRecord.punch_out_time.isnot(None)
        ).all()
        
        logger.info(f"Found {len(records)} records with both punches to recalculate.")
        
        if not records:
            logger.info("Nothing to update.")
            return

        updated_count = 0
        changed_count = 0
        for record in records:
            staff = db.query(Staff).filter(Staff.id == record.staff_id).first()
            if not staff:
                logger.warning(f"Staff missing for record ID {record.id}, skipping.")
                continue
                
            on_weekly_off = is_weekly_off(record.date, staff.weekly_off)
            
            # Recalculate hours with current rounding logic
            hours = calculate_work_hours(
                record.punch_in_time,
                record.punch_out_time,
                shift_start_str=staff.shift_start,
                shift_end_str=staff.shift_end,
                is_weekly_off_day=on_weekly_off,
            )
            
            # Recalculate status
            new_status = determine_status(
                record.punch_in_time,
                record.punch_out_time,
                is_weekly_off=on_weekly_off,
                regular_minutes=hours["regular_minutes"],
                shift_start_str=staff.shift_start,
                shift_end_str=staff.shift_end,
            )
            
            # Track what changed for logging
            old_ot = record.ot_minutes
            old_total = record.total_work_minutes
            old_regular = record.regular_minutes
            old_status = record.status
            
            record.total_work_minutes = hours["total_work_minutes"]
            record.regular_minutes = hours["regular_minutes"]
            record.ot_minutes = hours["ot_minutes"]
            record.status = new_status
            
            has_changes = (
                old_ot != record.ot_minutes or
                old_total != record.total_work_minutes or
                old_regular != record.regular_minutes or
                old_status != record.status
            )
            
            if has_changes:
                changed_count += 1
                logger.info(
                    f"CHANGED Record ID={record.id} Date={record.date} "
                    f"Staff={staff.employee_id} "
                    f"| Status: '{old_status}' -> '{record.status}' "
                    f"| OT: {old_ot}m -> {record.ot_minutes}m "
                    f"| Regular: {old_regular}m -> {record.regular_minutes}m "
                    f"| Total: {old_total}m -> {record.total_work_minutes}m"
                )
            
            updated_count += 1
            
        db.commit()
        logger.info(
            f"Migration completed. Processed {updated_count} records, "
            f"{changed_count} had changes applied."
        )

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    logger.info(
        "Starting full attendance recalculation "
        "(OT rounding + Sunday/weekly-off status migration)..."
    )
    run_migration()
