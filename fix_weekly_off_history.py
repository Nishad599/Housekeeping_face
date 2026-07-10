"""
One-time repair script: fixes historical attendance records where a staff
member worked on their WEEKLY OFF day but the record was saved as
Present/Partial (with hours split into regular + OT).

After the fix:
  - status  -> "Weekly Off"
  - regular_minutes -> 0
  - ot_minutes      -> full worked time as OT (lunch/rounding rules applied)

Run:  python fix_weekly_off_history.py            (dry run — shows what would change)
      python fix_weekly_off_history.py --apply    (actually writes changes)
"""
import sys
from datetime import datetime

from app.database import SessionLocal
from app.models.staff import Staff
from app.models.attendance import AttendanceRecord
from app.services.ot_service import is_weekly_off, calculate_work_hours
from app.services.attendance_service import log_audit

APPLY = "--apply" in sys.argv


def main():
    db = SessionLocal()
    fixed = 0
    try:
        staff_map = {s.id: s for s in db.query(Staff).all()}
        records = db.query(AttendanceRecord).filter(
            AttendanceRecord.status.in_(["Present", "Partial"])
        ).all()

        for rec in records:
            staff = staff_map.get(rec.staff_id)
            if not staff:
                continue
            if not is_weekly_off(rec.date, staff.weekly_off):
                continue

            old = (rec.status, rec.regular_minutes, rec.ot_minutes)

            if rec.punch_in_time and rec.punch_out_time:
                hours = calculate_work_hours(
                    rec.punch_in_time, rec.punch_out_time,
                    shift_start_str=staff.shift_start,
                    shift_end_str=staff.shift_end,
                    is_weekly_off_day=True,
                )
                rec.total_work_minutes = hours["total_work_minutes"]
                rec.regular_minutes = hours["regular_minutes"]   # 0
                rec.ot_minutes = hours["ot_minutes"]
            else:
                rec.regular_minutes = 0

            rec.status = "Weekly Off"
            fixed += 1
            print(f"[{'FIX' if APPLY else 'DRY'}] {staff.employee_id} {staff.name} "
                  f"{rec.date}: {old} -> ('Weekly Off', {rec.regular_minutes}, {rec.ot_minutes})")

            if APPLY:
                log_audit(db, "FIX_WEEKLY_OFF", "attendance", rec.id,
                          performed_by="fix_script", details={
                              "old_status": old[0],
                              "old_regular": old[1], "old_ot": old[2],
                              "new_ot": rec.ot_minutes,
                          })

        if APPLY:
            db.commit()
            print(f"\n✅ {fixed} record(s) repaired and committed.")
        else:
            db.rollback()
            print(f"\n(dry run) {fixed} record(s) WOULD be repaired. "
                  f"Run again with --apply to write changes.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
