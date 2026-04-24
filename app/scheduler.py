"""
Daily absence alert scheduler.

Uses APScheduler to run a job every day at ABSENCE_ALERT_TIME (default 18:00 IST).
Queries all active staff with no attendance record for the day (excluding weekly-off)
and sends a batched absence alert via the notification service.

Start/stop are handled by FastAPI's lifespan context manager in main.py.
"""
import logging
import os
from datetime import date, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
ABSENCE_ALERT_TIME = os.getenv("ABSENCE_ALERT_TIME", "18:00")   # HH:MM IST
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

scheduler = AsyncIOScheduler(timezone=TIMEZONE)


async def _run_absence_check():
    """
    Daily job: find all active staff with no attendance record today
    (excluding weekly-off) and send a batched alert.
    """
    from app.database import SessionLocal
    from app.models.staff import Staff
    from app.models.attendance import AttendanceRecord
    from app.services.ot_service import is_weekly_off as check_weekly_off
    from app.services.notification_service import send_bulk_absent_alert

    today = date.today()
    date_str = today.strftime("%A, %d %B %Y")

    db: Session = SessionLocal()
    try:
        all_active_staff = db.query(Staff).filter(Staff.is_active == True).all()

        # Staff who DID punch today
        punched_ids = set(
            r.staff_id
            for r in db.query(AttendanceRecord).filter(
                AttendanceRecord.date == today
            ).all()
        )

        absent_staff = []
        for staff in all_active_staff:
            if staff.id in punched_ids:
                continue
            if check_weekly_off(today, staff.weekly_off):
                continue   # Skip weekly-off day
            absent_staff.append({"employee_id": staff.employee_id, "name": staff.name})

        if absent_staff:
            logger.info(
                f"Absence alert: {len(absent_staff)} absent staff on {today}"
            )
            send_bulk_absent_alert(absent_staff, date_str)
        else:
            logger.info(f"Absence check: all staff present on {today}")
    except Exception as exc:
        logger.error(f"Absence check job failed: {exc}", exc_info=True)
    finally:
        db.close()


def start_scheduler():
    """Start the APScheduler. Call from FastAPI lifespan startup."""
    try:
        hour, minute = ABSENCE_ALERT_TIME.split(":")
        scheduler.add_job(
            _run_absence_check,
            trigger=CronTrigger(hour=int(hour), minute=int(minute)),
            id="daily_absence_alert",
            replace_existing=True,
            misfire_grace_time=300,
        )
        scheduler.start()
        logger.info(
            f"Absence alert scheduler started — "
            f"will run daily at {ABSENCE_ALERT_TIME} {TIMEZONE}"
        )
    except Exception as exc:
        logger.error(f"Failed to start scheduler: {exc}", exc_info=True)


def stop_scheduler():
    """Gracefully stop the scheduler. Call from FastAPI lifespan shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Absence alert scheduler stopped")
