"""
Notification Service — SMS/Email alerts for absent staff.

Transports are configured via environment variables.
If no transport is configured, all calls silently no-op (no crash, no error).

Email (SMTP):
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO

SMS (Twilio REST):
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, TWILIO_TO

Both transports can be active simultaneously.
"""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

SMTP_HOST    = os.getenv("SMTP_HOST", "")
SMTP_PORT    = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER    = os.getenv("SMTP_USER", "")
SMTP_PASS    = os.getenv("SMTP_PASS", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")   # comma-separated for multiple

TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM         = os.getenv("TWILIO_FROM", "")
TWILIO_TO           = os.getenv("TWILIO_TO", "")   # comma-separated for multiple


def _email_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS and ALERT_EMAIL_TO)


def _twilio_configured() -> bool:
    return bool(
        TWILIO_ACCOUNT_SID
        and TWILIO_AUTH_TOKEN
        and TWILIO_FROM
        and TWILIO_TO
    )


# ── Email ─────────────────────────────────────────────────────────────────────

def _send_email(subject: str, body: str) -> bool:
    """Send an email via SMTP. Returns True on success."""
    try:
        recipients = [r.strip() for r in ALERT_EMAIL_TO.split(",") if r.strip()]
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = ", ".join(recipients)
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(body.replace("\n", "<br>"), "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, recipients, msg.as_string())

        logger.info(f"Absence alert email sent to {recipients}")
        return True
    except Exception as exc:
        logger.error(f"Email send failed: {exc}")
        return False


# ── Twilio SMS ────────────────────────────────────────────────────────────────

def _send_sms(body: str) -> bool:
    """Send SMS via Twilio REST API (no SDK needed). Returns True on success."""
    try:
        import httpx  # optional dependency

        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/"
            f"{TWILIO_ACCOUNT_SID}/Messages.json"
        )
        recipients = [r.strip() for r in TWILIO_TO.split(",") if r.strip()]
        success = True
        for to_num in recipients:
            resp = httpx.post(
                url,
                data={"From": TWILIO_FROM, "To": to_num, "Body": body},
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                timeout=10,
            )
            if resp.status_code not in (200, 201):
                logger.error(f"Twilio SMS to {to_num} failed: {resp.text}")
                success = False
            else:
                logger.info(f"Absence alert SMS sent to {to_num}")
        return success
    except ImportError:
        logger.warning("httpx not installed — Twilio SMS skipped")
        return False
    except Exception as exc:
        logger.error(f"SMS send failed: {exc}")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def send_absent_alert(staff_name: str, employee_id: str, date_str: str) -> None:
    """
    Send an absence alert for a single staff member via all configured transports.
    Silently no-ops if neither transport is configured.
    """
    if not _email_configured() and not _twilio_configured():
        return

    subject = f"[Attendance Alert] {employee_id} – {staff_name} absent on {date_str}"
    body = (
        f"ATTENDANCE ALERT\n"
        f"{'='*40}\n"
        f"Employee : {staff_name} ({employee_id})\n"
        f"Date     : {date_str}\n"
        f"Status   : ABSENT — no punch recorded\n"
        f"{'='*40}\n"
        f"Please check the attendance dashboard.\n"
    )

    if _email_configured():
        _send_email(subject, body)

    if _twilio_configured():
        _send_sms(
            f"[Attendance] {employee_id} {staff_name} is ABSENT on {date_str}. "
            "Check dashboard."
        )


def send_bulk_absent_alert(absent_staff: List[dict], date_str: str) -> None:
    """
    Send a single batched email / SMS listing all absent staff for the day.
    Silently no-ops if neither transport is configured.
    absent_staff: list of {"employee_id": ..., "name": ...}
    """
    if not absent_staff:
        return
    if not _email_configured() and not _twilio_configured():
        return

    names = "\n".join(
        f"  • {s['employee_id']} – {s['name']}" for s in absent_staff
    )
    subject = f"[Attendance Alert] {len(absent_staff)} staff absent on {date_str}"
    body = (
        f"DAILY ABSENCE REPORT — {date_str}\n"
        f"{'='*40}\n"
        f"The following {len(absent_staff)} staff member(s) did not punch in today:\n\n"
        f"{names}\n\n"
        f"{'='*40}\n"
        f"Please check the attendance dashboard for details.\n"
    )

    sms_body = (
        f"[Attendance] {len(absent_staff)} absent on {date_str}: "
        + ", ".join(s["employee_id"] for s in absent_staff)
    )

    if _email_configured():
        _send_email(subject, body)

    if _twilio_configured():
        _send_sms(sms_body)
