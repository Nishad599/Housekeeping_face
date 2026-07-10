"""
Authentication API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.limiter import limiter

from app.database import get_db
from app.config import settings
from app.schemas import (
    LoginRequest, TokenResponse, UserCreate,
    ChangePasswordRequest, ResetPasswordRequest,
)
from app.models.user import User, UserRole
from app.auth.auth_service import (
    hash_password, verify_password, create_token, require_role
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
@limiter.limit("5/minute")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")

    token = create_token({"sub": user.username, "role": user.role})

    response = JSONResponse(content={
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "full_name": user.full_name,
    })
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout():
    """Clear the session cookie."""
    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie(key="access_token", path="/")
    return response


@router.post("/change-password")
@limiter.limit("5/minute")
def change_password(
    req: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "supervisor", "viewer")),
):
    """Change the logged-in user's own password (requires current password)."""
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if req.new_password == req.old_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one")

    user.password_hash = hash_password(req.new_password)
    db.commit()
    return {"message": "Password changed successfully. Please log in again."}


@router.post("/reset-password/{username}")
def reset_user_password(
    username: str,
    req: ResetPasswordRequest,
    db: Session = Depends(get_db),
    admin=Depends(require_role("admin")),
):
    """Admin resets another user's password (no old password needed)."""
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    target.password_hash = hash_password(req.new_password)
    db.commit()
    return {"message": f"Password reset for user '{username}'"}


@router.post("/register")
def register_user(
    req: UserCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_role("admin")),
):
    existing = db.query(User).filter(User.username == req.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        role=req.role,
    )
    db.add(user)
    db.commit()
    return {"message": f"User '{req.username}' created with role '{req.role}'"}
