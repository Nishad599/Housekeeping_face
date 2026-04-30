"""
Staff Management API routes.
"""
import io
import csv
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.schemas import StaffCreate, StaffUpdate, StaffResponse, BulkUploadResult
from app.models.staff import Staff, FaceEmbedding
from app.models.attendance import AttendancePunch, AttendanceRecord
from app.models.audit import AuditLog
from app.services.face_service import register_face, register_face_multi, load_embedding_cache
from app.auth.auth_service import require_role, get_current_user
import json

router = APIRouter(prefix="/api/staff", tags=["staff"])


@router.get("/", response_model=List[StaffResponse])
def list_staff(
    active_only: bool = True,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "supervisor", "viewer")),
):
    query = db.query(Staff)
    if active_only:
        query = query.filter(Staff.is_active == True)
    staff_list = query.order_by(Staff.employee_id).all()

    results = []
    for s in staff_list:
        has_face = db.query(FaceEmbedding).filter(
            FaceEmbedding.staff_id == s.id,
            FaceEmbedding.is_active == True
        ).first() is not None

        results.append(StaffResponse(
            id=s.id,
            employee_id=s.employee_id,
            name=s.name,
            designation=s.designation,
            phone=s.phone,
            location=s.location,
            shift_start=s.shift_start or "07:00",
            shift_end=s.shift_end or "16:00",
            weekly_off=s.weekly_off or "Sunday",
            is_active=s.is_active,
            has_face=has_face,
            created_at=s.created_at,
        ))
    return results


@router.post("/")
def add_staff(
    req: StaffCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "supervisor")),
):
    existing = db.query(Staff).filter(Staff.employee_id == req.employee_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Employee ID '{req.employee_id}' already exists")

    staff = Staff(
        employee_id=req.employee_id,
        name=req.name,
        designation=req.designation,
        phone=req.phone,
        location=req.location,
        shift_start=req.shift_start,
        shift_end=req.shift_end,
        weekly_off=req.weekly_off,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)

    return {"message": f"Staff '{req.name}' added", "id": staff.id, "employee_id": staff.employee_id}


@router.put("/{employee_id}")
def update_staff(
    employee_id: str,
    req: StaffUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "supervisor")),
):
    staff = db.query(Staff).filter(Staff.employee_id == employee_id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    for field, value in req.model_dump(exclude_none=True).items():
        setattr(staff, field, value)
    db.commit()
    return {"message": f"Staff '{employee_id}' updated"}


@router.post("/{employee_id}/register-face")
async def register_face_route(
    employee_id: str,
    face_image: UploadFile = File(...),
    face_image_2: Optional[UploadFile] = File(None),
    face_image_3: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "supervisor")),
):
    """
    Register face for a staff member.
    Accepts 1–3 photos; if multiple are provided the embeddings are averaged
    for better recognition accuracy.
    """
    staff = db.query(Staff).filter(Staff.employee_id == employee_id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    # Collect all uploaded image bytes
    image_bytes_list = [await face_image.read()]
    if face_image_2:
        image_bytes_list.append(await face_image_2.read())
    if face_image_3:
        image_bytes_list.append(await face_image_3.read())

    if len(image_bytes_list) > 1:
        success, message = register_face_multi(
            staff.id, image_bytes_list, db, registered_by="admin"
        )
    else:
        success, message = register_face(
            staff.id, image_bytes_list[0], db, registered_by="admin"
        )

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"message": message, "employee_id": employee_id}



@router.post("/bulk-upload")
async def bulk_upload_staff(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "supervisor")),
):
    """
    Bulk add staff from CSV.
    Expected columns: employee_id, name, designation, phone
    """
    content = await file.read()
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))

    total = 0
    success = 0
    errors = []

    for row in reader:
        total += 1
        emp_id = row.get("employee_id", "").strip()
        name = row.get("name", "").strip()
        designation = row.get("designation", "").strip()
        phone = row.get("phone", "").strip()

        if not emp_id:
            errors.append(f"Row {total}: Missing employee_id")
            continue
        if not name:
            errors.append(f"Row {total}: Missing name for {emp_id}")
            continue

        existing = db.query(Staff).filter(Staff.employee_id == emp_id).first()
        if existing:
            errors.append(f"Row {total}: Duplicate employee_id '{emp_id}'")
            continue

        staff = Staff(
            employee_id=emp_id,
            name=name,
            designation=designation if designation else None,
            phone=phone if phone else None,
        )
        db.add(staff)
        success += 1

    db.commit()
    return BulkUploadResult(total=total, success=success, failed=total - success, errors=errors)


@router.post("/{employee_id}/toggle")
def toggle_staff_status(
    employee_id: str,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "supervisor")),
):
    """Toggle staff active/inactive status."""
    staff = db.query(Staff).filter(Staff.employee_id == employee_id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    staff.is_active = not staff.is_active
    db.commit()
    status = "activated" if staff.is_active else "deactivated"
    return {"message": f"Staff '{employee_id}' {status}"}


@router.delete("/{employee_id}")
def remove_staff(
    employee_id: str,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    """Hard delete staff member (admin only)."""
    staff = db.query(Staff).filter(Staff.employee_id == employee_id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    
    try:
        # Delete associated data in correct order to satisfy foreign key constraints
        db.query(FaceEmbedding).filter(FaceEmbedding.staff_id == staff.id).delete(synchronize_session=False)
        db.query(AttendancePunch).filter(AttendancePunch.staff_id == staff.id).delete(synchronize_session=False)
        db.query(AttendanceRecord).filter(AttendanceRecord.staff_id == staff.id).delete(synchronize_session=False)
        
        # Finally delete the staff member
        db.delete(staff)
        db.commit()
        return {"message": f"Staff member '{employee_id}' has been permanently removed."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error while removing staff: {str(e)}")
