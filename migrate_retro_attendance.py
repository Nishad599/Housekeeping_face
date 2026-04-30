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
    Recalculate attendance records from March 29, 2026 to present 
    using the new 15-minute punch-in rounding logic.
    """
    db: Session = SessionLocal()
    target_date = date(2026, 3, 29)
    
    try:
        # Get all records from target_date onwards that have both punch in and out
        records = db.query(AttendanceRecord).filter(
            AttendanceRecord.date >= target_date,
            AttendanceRecord.punch_in_time.isnot(None),
            AttendanceRecord.punch_out_time.isnot(None)
        ).all()
        
        logger.info(f"Found {len(records)} records satisfying date >= {target_date} with both punches.")
        
        if not records:
            logger.info("Nothing to update.")
            return

        updated_count = 0
        for record in records:
            staff = db.query(Staff).filter(Staff.id == record.staff_id).first()
            if not staff:
                logger.warning(f"Staff missing for record ID {record.id}, skipping.")
                continue
                
            on_weekly_off = is_weekly_off(record.date, staff.weekly_off)
            
            # Recalculate hours (which now uses the 15-minute round-up inside ot_service)
            hours = calculate_work_hours(
                record.punch_in_time,
                record.punch_out_time,
                shift_start_str=staff.shift_start,
                shift_end_str=staff.shift_end,
                is_weekly_off_day=on_weekly_off,
            )
            
            # Recalculate status based on the new hours
            new_status = determine_status(
                record.punch_in_time,
                record.punch_out_time,
                is_weekly_off=on_weekly_off,
                regular_minutes=hours["regular_minutes"],
                shift_start_str=staff.shift_start,
                shift_end_str=staff.shift_end,
            )
            
            # Compare previous values for logging (optional, debugging)
            old_ot = record.ot_minutes
            old_total = record.total_work_minutes
            
            record.total_work_minutes = hours["total_work_minutes"]
            record.regular_minutes = hours["regular_minutes"]
            record.ot_minutes = hours["ot_minutes"]
            record.status = new_status
            
            if old_ot != record.ot_minutes or old_total != record.total_work_minutes:
                logger.info(
                    f"Updated Record ID={record.id} Date={record.date} Staff={staff.employee_id} "
                    f"| OT {old_ot}m -> {record.ot_minutes}m, Total {old_total}m -> {record.total_work_minutes}m"
                )
            
            updated_count += 1
            
        db.commit()
        logger.info(f"Migration completed successfully. Recalculated {updated_count} records.")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("Starting attendance hour recalculation (15-min round-up migration)...")
    run_migration()
