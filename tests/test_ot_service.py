"""
Unit tests for ot_service.py

Tests cover:
  - Normal day-shift: exact shift window = regular only, excess = OT
  - Weekly-off day: ALL time = OT, regular = 0
  - Cross-midnight night shift: correct duration cap and OT split
  - OT rounding to nearest 15-min block
  - determine_status for weekly-off punch (should be Present)
"""
import pytest
from datetime import datetime, date
from unittest.mock import patch

# Patch settings so tests don't need a real .env
import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-chars-minimum!!")
os.environ.setdefault("SHIFT_START", "07:00")
os.environ.setdefault("SHIFT_END", "16:00")


from app.services.ot_service import (
    calculate_work_hours,
    round_ot_minutes,
    get_shift_duration_minutes,
    determine_status,
    is_weekly_off,
    is_cross_midnight,
    parse_time,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def dt(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")


# ─── get_shift_duration_minutes ───────────────────────────────────────────────

def test_day_shift_duration():
    # 07:00 → 16:00 = 9h = 540min
    mins = get_shift_duration_minutes("07:00", "16:00")
    assert mins == 540


def test_night_shift_duration():
    # 22:00 → 06:00 = 8h = 480min
    mins = get_shift_duration_minutes("22:00", "06:00")
    assert mins == 480


def test_is_cross_midnight():
    assert is_cross_midnight(parse_time("22:00"), parse_time("06:00")) is True
    assert is_cross_midnight(parse_time("07:00"), parse_time("16:00")) is False


# ─── calculate_work_hours — day shift ─────────────────────────────────────────

def test_normal_day_exact_shift():
    """Exactly 9 hours → regular=540, ot=0."""
    result = calculate_work_hours(
        dt("2024-01-15", "07:00"),
        dt("2024-01-15", "16:00"),
        shift_start_str="07:00",
        shift_end_str="16:00",
    )
    assert result["regular_minutes"] == 540
    assert result["ot_minutes"] == 0
    assert result["total_work_minutes"] == 540


def test_normal_day_with_ot():
    """9h shift + 2h OT → regular=540, ot=120."""
    result = calculate_work_hours(
        dt("2024-01-15", "07:00"),
        dt("2024-01-15", "18:00"),
        shift_start_str="07:00",
        shift_end_str="16:00",
    )
    assert result["regular_minutes"] == 540
    assert result["ot_minutes"] == 120        # 2h rounds to 120 exactly
    assert result["total_work_minutes"] == 660


def test_ot_rounded_to_15():
    """OT of 32 minutes → rounds up to 30, then 22 → 15."""
    assert round_ot_minutes(32) == 30
    assert round_ot_minutes(22) == 15
    assert round_ot_minutes(7) == 0
    assert round_ot_minutes(8) == 15


def test_less_than_full_shift():
    """5h on a 9h shift → regular=300, ot=0."""
    result = calculate_work_hours(
        dt("2024-01-15", "07:00"),
        dt("2024-01-15", "12:00"),
        shift_start_str="07:00",
        shift_end_str="16:00",
    )
    assert result["regular_minutes"] == 300
    assert result["ot_minutes"] == 0


# ─── calculate_work_hours — weekly off → all OT ───────────────────────────────

def test_weekly_off_all_ot():
    """4h on weekly-off day → regular=0, ot=240 (all OT)."""
    result = calculate_work_hours(
        dt("2024-01-14", "09:00"),   # a Sunday
        dt("2024-01-14", "13:00"),
        shift_start_str="07:00",
        shift_end_str="16:00",
        is_weekly_off_day=True,
    )
    assert result["regular_minutes"] == 0
    assert result["ot_minutes"] == 240
    assert result["total_work_minutes"] == 240


def test_weekly_off_full_shift_all_ot():
    """Full 9h on weekly-off → regular=0, ot=480 (540 - 60m lunch)."""
    result = calculate_work_hours(
        dt("2024-01-14", "07:00"),
        dt("2024-01-14", "16:00"),
        is_weekly_off_day=True,
    )
    assert result["regular_minutes"] == 0
    assert result["ot_minutes"] == 480


# ─── calculate_work_hours — night shift ───────────────────────────────────────

def test_night_shift_within_window():
    """Night shift 22:00 → 04:00 (6h) within 8h window → regular=360, ot=0."""
    result = calculate_work_hours(
        dt("2024-01-15", "22:00"),
        dt("2024-01-16", "04:00"),
        shift_start_str="22:00",
        shift_end_str="06:00",   # 8h window
    )
    assert result["total_work_minutes"] == 360
    assert result["regular_minutes"] == 360
    assert result["ot_minutes"] == 0


def test_night_shift_with_ot():
    """Night shift 22:00 → 08:00 (10h) with 8h window → regular=480, ot=120."""
    result = calculate_work_hours(
        dt("2024-01-15", "22:00"),
        dt("2024-01-16", "08:00"),
        shift_start_str="22:00",
        shift_end_str="06:00",   # 8h = 480min cap
    )
    assert result["total_work_minutes"] == 600
    assert result["regular_minutes"] == 480
    assert result["ot_minutes"] == 120


# ─── determine_status ─────────────────────────────────────────────────────────

def test_present_on_weekly_off():
    """If someone punches in on their weekly off and works a full shift, they are Present."""
    status = determine_status(
        punch_in=dt("2024-01-14", "07:00"),
        punch_out=dt("2024-01-14", "16:00"),
        is_weekly_off=True,
        regular_minutes=0,  # all OT on weekly off
        shift_start_str="07:00",
        shift_end_str="16:00",
    )
    assert status == "Present"


def test_absent():
    status = determine_status(punch_in=None, punch_out=None)
    assert status == "Absent"


def test_weekly_off_no_punch():
    status = determine_status(punch_in=None, punch_out=None, is_weekly_off=True)
    assert status == "Weekly Off"


def test_partial_less_than_half_shift():
    status = determine_status(
        punch_in=dt("2024-01-15", "07:00"),
        punch_out=dt("2024-01-15", "09:00"),
        is_weekly_off=False,
        regular_minutes=120,   # 2h out of 9h — < 50%
        shift_start_str="07:00",
        shift_end_str="16:00",
    )
    assert status == "Partial"


# ─── is_weekly_off ────────────────────────────────────────────────────────────

def test_is_weekly_off_sunday():
    sunday = date(2024, 1, 14)  # This is a Sunday
    assert is_weekly_off(sunday, "Sunday") is True
    assert is_weekly_off(sunday, "Monday") is False


def test_is_weekly_off_saturday():
    saturday = date(2024, 1, 13)
    assert is_weekly_off(saturday, "Saturday") is True
