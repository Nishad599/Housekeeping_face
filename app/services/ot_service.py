"""
Overtime & Working Hours Calculation Service

Rules:
- Standard shift: 7:00 AM - 4:00 PM (configurable per staff)
- Regular hours: capped at the configured shift window duration
- OT hours: any time beyond the shift window cap
- Cross-midnight shifts: shift_end < shift_start (e.g. 22:00 → 06:00)
- OT rounding: to nearest 15-minute block
- OT minimum: must be >= 60 minutes, otherwise zeroed out
- Grace period: 30 minutes after shift end — not counted as OT
- Working days: 6 per week (configurable)
- Weekly-off day: ALL minutes count as OT; status stays "Weekly Off"
"""
from datetime import datetime, time, timedelta, date
from typing import Tuple, Optional
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# ── Configurable thresholds ──────────────────────────────────
GRACE_PERIOD_MINUTES = 0    # Let OT_MINIMUM_MINUTES handle the threshold
OT_MINIMUM_MINUTES = 30     # OT below 30 min is zeroed out


def parse_time(t_str: str) -> time:
    """Parse 'HH:MM' string to time object."""
    parts = t_str.split(":")
    return time(int(parts[0]), int(parts[1]))


def is_cross_midnight(shift_start: time, shift_end: time) -> bool:
    """True if the shift spans midnight (e.g. 22:00 → 06:00)."""
    return shift_end <= shift_start


def get_shift_duration_minutes(
    shift_start_str: Optional[str] = None,
    shift_end_str: Optional[str] = None,
) -> int:
    """
    Return the total designed shift window in minutes.
    Handles cross-midnight shifts correctly.
    """
    start_str = shift_start_str or settings.SHIFT_START
    end_str = shift_end_str or settings.SHIFT_END
    start = parse_time(start_str)
    end = parse_time(end_str)

    base_date = datetime(2000, 1, 1)
    dt_start = datetime.combine(base_date, start)
    dt_end = datetime.combine(base_date, end)

    if is_cross_midnight(start, end):
        dt_end += timedelta(days=1)

    return int((dt_end - dt_start).total_seconds() / 60)


def get_shift_times(
    shift_start_str: Optional[str] = None,
    shift_end_str: Optional[str] = None,
) -> Tuple[time, time]:
    """Get shift start and end times (from staff config or global defaults)."""
    start_str = shift_start_str or settings.SHIFT_START
    end_str = shift_end_str or settings.SHIFT_END
    return parse_time(start_str), parse_time(end_str)


def apply_grace_period(total_minutes: int, shift_cap: int) -> int:
    """
    Apply grace period: if total work is within (shift_cap + grace),
    treat it as exactly shift_cap (no OT).
    
    Example: Shift is 540 min (9 hrs). Grace is 30 min.
    - Worked 555 min → treated as 540 (no OT)
    - Worked 575 min → 575 - 540 = 35 min OT (beyond grace)
    """
    grace_cap = shift_cap + GRACE_PERIOD_MINUTES
    if total_minutes <= grace_cap:
        return min(total_minutes, shift_cap)  # clamp to shift_cap, no OT
    return total_minutes  # beyond grace, full OT applies


def apply_ot_minimum(ot_minutes: int) -> int:
    """
    Zero out OT if it's less than the minimum threshold (60 min).
    Only OT of 1 hour or more is counted.
    """
    if ot_minutes < OT_MINIMUM_MINUTES:
        return 0
    return ot_minutes


def round_up_15m(dt: datetime) -> datetime:
    """Round up datetime to next 15-minute block."""
    if dt.minute % 15 == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt
    discard = timedelta(seconds=dt.second, microseconds=dt.microsecond)
    add_mins = 15 - (dt.minute % 15)
    return dt - discard + timedelta(minutes=add_mins)


def calculate_work_hours(
    punch_in: datetime,
    punch_out: datetime,
    shift_start_str: Optional[str] = None,
    shift_end_str: Optional[str] = None,
    is_weekly_off_day: bool = False,
) -> dict:
    """
    Calculate regular and OT minutes from punch-in/out.

    Logic:
    1. Apply 15-minute round-up to punch-in time (e.g., 06:46 -> 07:00).
    2. Total work = punch_out - punch_in (raw minutes).

    2. If is_weekly_off_day → ALL time is OT; regular = 0.
       - OT minimum (60 min) still applies.
    3. Otherwise:
       - Regular hours cap = actual shift window duration.
       - Grace period: 30 min after shift end is NOT OT.
       - OT minimum: anything under 60 min OT is zeroed.
       - Regular minutes = min(total_minutes, cap).
       - OT minutes = excess beyond the cap (after grace & minimum).
    4. OT rounded to nearest 15-min block.

    Returns dict with: total_work_minutes, regular_minutes, ot_minutes
    """
    # Apply round up to punch-in time
    punch_in = round_up_15m(punch_in)
    
    if punch_out <= punch_in:
        return {"total_work_minutes": 0, "regular_minutes": 0, "ot_minutes": 0}

    total_minutes = int((punch_out - punch_in).total_seconds() / 60)

    if is_weekly_off_day:
        # Weekly-off day → every minute is OT
        effective_ot = total_minutes
        # Deduct 1 hour (lunch) if working more than 8 hours on off-day
        if total_minutes > 480:
            effective_ot = total_minutes - 60
        
        ot_rounded = round_ot_minutes(effective_ot)
        # Apply OT minimum: no OT if under 1 hour
        ot_minutes = apply_ot_minimum(ot_rounded)
        regular_minutes = 0
        logger.debug(
            f"Weekly-off punch: total={total_minutes}m → OT (raw={total_minutes}, "
            f"rounded={ot_rounded}, after minimum={ot_minutes})"
        )
    else:
        # Use the configured shift window as the regular-hours cap
        shift_cap = get_shift_duration_minutes(shift_start_str, shift_end_str)

        # Apply grace period: absorb up to 30 min past shift end
        effective_minutes = apply_grace_period(total_minutes, shift_cap)

        if effective_minutes <= shift_cap:
            regular_minutes = min(total_minutes, shift_cap)
            ot_minutes = 0
        else:
            regular_minutes = shift_cap
            raw_ot = effective_minutes - shift_cap
            ot_rounded = round_ot_minutes(raw_ot)
            # Apply OT minimum: no OT if under 1 hour
            ot_minutes = apply_ot_minimum(ot_rounded)

        logger.debug(
            f"Regular punch: total={total_minutes}m, shift_cap={shift_cap}m, "
            f"effective={effective_minutes}m, regular={regular_minutes}m, ot={ot_minutes}m"
        )

    return {
        "total_work_minutes": total_minutes,
        "regular_minutes": regular_minutes,
        "ot_minutes": ot_minutes,
    }


def round_ot_minutes(minutes: int) -> int:
    """
    Round OT to nearest 15-minute block.
    0-7 min → 0, 8-22 min → 15, 23-37 min → 30, etc.
    """
    if minutes <= 0:
        return 0
    blocks = minutes / 15
    return round(blocks) * 15


def format_hours_minutes(total_minutes: int) -> str:
    """Format minutes as 'Xh Ym'."""
    if total_minutes <= 0:
        return "0h 0m"
    hours = total_minutes // 60
    mins = total_minutes % 60
    return f"{hours}h {mins}m"


def determine_status(
    punch_in: Optional[datetime],
    punch_out: Optional[datetime],
    is_weekly_off: bool = False,
    regular_minutes: int = 0,
    shift_start_str: Optional[str] = None,
    shift_end_str: Optional[str] = None,
) -> str:
    """
    Determine attendance status for a day.
    
    Key change: Weekly off stays "Weekly Off" even if staff worked that day.
    OT is still calculated but status remains "Weekly Off".
    """
    if is_weekly_off and punch_in is None:
        return "Weekly Off"

    # Staff came on their weekly off → status stays "Weekly Off" (OT still calculated)
    if is_weekly_off:
        return "Weekly Off"

    if punch_in is None and punch_out is None:
        return "Absent"

    if punch_in is not None and punch_out is None:
        return "Partial"

    if punch_out is not None and punch_in is None:
        return "Invalid"

    # For night/cross-midnight shifts, expected duration uses shift window
    expected_minutes = get_shift_duration_minutes(shift_start_str, shift_end_str)

    # Calculate total duration in minutes
    total_duration = 0
    if punch_in and punch_out:
        total_duration = int((punch_out - punch_in).total_seconds() / 60)

    # If worked at least 8 hours 30 minutes, it's a full day regardless of shift duration
    if total_duration >= 510:
        return "Present"

    # If worked less than half the shift, mark as partial
    if regular_minutes < expected_minutes * 0.5:
        return "Partial"

    return "Present"


def is_weekly_off(check_date: date, weekly_off_day: str = None) -> bool:
    """Check if a given date is the weekly off day."""
    off_day = weekly_off_day or settings.DEFAULT_WEEKLY_OFF
    day_names = {
        "Monday": 0, "Tuesday": 1, "Wednesday": 2,
        "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6
    }
    off_index = day_names.get(off_day, 6)
    return check_date.weekday() == off_index