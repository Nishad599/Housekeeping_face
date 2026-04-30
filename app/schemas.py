"""
Pydantic schemas for request/response validation.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime, date
import re


# ─── Staff ─────────────────────────────────────────
class StaffCreate(BaseModel):
    employee_id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    designation: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    shift_start: Optional[str] = "07:00"
    shift_end: Optional[str] = "16:00"
    weekly_off: Optional[str] = "Sunday"

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if v and not re.match(r"^[\d\+\-\s]{7,20}$", v):
            raise ValueError("Invalid phone number format")
        return v


class StaffUpdate(BaseModel):
    name: Optional[str] = None
    designation: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    weekly_off: Optional[str] = None
    is_active: Optional[bool] = None


class StaffResponse(BaseModel):
    id: int
    employee_id: str
    name: str
    designation: Optional[str]
    phone: Optional[str]
    location: Optional[str]
    shift_start: str
    shift_end: str
    weekly_off: str
    is_active: bool
    has_face: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Attendance ────────────────────────────────────
class PunchResponse(BaseModel):
    success: bool
    message: str
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    punch_type: Optional[str] = None
    punch_time: Optional[datetime] = None
    confidence: Optional[float] = None


class AttendanceRecordResponse(BaseModel):
    id: int
    employee_id: str
    name: str
    date: date
    punch_in_time: Optional[datetime]
    punch_out_time: Optional[datetime]
    total_work_minutes: int
    regular_minutes: int
    ot_minutes: int
    status: str
    is_edited: bool

    class Config:
        from_attributes = True


class AttendanceEditRequest(BaseModel):
    punch_in_time: Optional[str] = None  # "HH:MM" format
    punch_out_time: Optional[str] = None
    status: Optional[str] = None
    edit_reason: str = Field(..., min_length=3)


class BulkManualMarkRequest(BaseModel):
    employee_ids: List[str]
    date: str  # "YYYY-MM-DD"
    punch_in_time: Optional[str] = None  # "HH:MM"
    punch_out_time: Optional[str] = None
    status: str = "Present"
    edit_reason: str = Field(..., min_length=3)


# ─── Muster Book ───────────────────────────────────
class MusterBookQuery(BaseModel):
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2020)
    employee_id: Optional[str] = None


# ─── Auth ──────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    full_name: str
    role: str = "viewer"


# ─── Bulk Upload ───────────────────────────────────
class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: List[str]
