"""
Authentication API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.limiter import limiter

from app.database import get_db
from app.config import settings
from app.schemas import LoginRequest, TokenResponse, UserCreate
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
