import os
import sys
from datetime import datetime
from sqlalchemy.orm import Session

# Add current directory to path so we can import app
sys.path.append(os.getcwd())

from app.database import SessionLocal
from app.models.attendance import AttendanceRecord
from app.models.staff import Staff
from app.services.ot_service import calculate_work_hours, determine_status, is_weekly_off

def recalculate_attendance(db: Session):
    print("Recalculating attendance status for all records...")
    records = db.query(AttendanceRecord).all()
    count = 0
    for rec in records:
        staff = db.query(Staff).filter(Staff.id == rec.staff_id).first()
        if not staff:
            continue

        if rec.punch_in_time and rec.punch_out_time:
            on_weekly_off = is_weekly_off(rec.date, staff.weekly_off)
            hours = calculate_work_hours(
                rec.punch_in_time,
                rec.punch_out_time,
                shift_start_str=staff.shift_start,
                shift_end_str=staff.shift_end,
                is_weekly_off_day=on_weekly_off,
            )
            rec.total_work_minutes = hours["total_work_minutes"]
            rec.regular_minutes = hours["regular_minutes"]
            rec.ot_minutes = hours["ot_minutes"]
            
            # Use the updated determine_status (with 8:30h rule)
            rec.status = determine_status(
                rec.punch_in_time,
                rec.punch_out_time,
                is_weekly_off=on_weekly_off,
                regular_minutes=hours["regular_minutes"],
                shift_start_str=staff.shift_start,
                shift_end_str=staff.shift_end,
            )
            count += 1

    db.commit()
    print(f"Successfully updated {count} records.")

if __name__ == "__main__":
    db = SessionLocal()
    try:
        recalculate_attendance(db)
    finally:
        db.close()
