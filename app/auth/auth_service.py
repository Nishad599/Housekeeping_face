"""
Authentication service - JWT tokens, password hashing, RBAC.
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Extract current user from JWT token.
    Returns None if no token (allows anonymous access for punch endpoints).
    """
    token = None

    # Check Authorization header
    if credentials:
        token = credentials.credentials

    # Also check cookie
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        return None

    payload = decode_token(token)
    if not payload:
        return None

    username = payload.get("sub")
    if not username:
        return None

    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    return user


def require_role(*roles: str):
    """Dependency: require user with specific role(s)."""
    def role_checker(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
        db: Session = Depends(get_db),
    ):
        user = get_current_user(request, credentials, db)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Role '{user.role}' not authorized. Need: {roles}")
        return user
    return role_checker


def init_default_admin(db: Session):
    """Create default admin user if none exists."""
    existing = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
    if not existing:
        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            full_name="System Administrator",
            role=UserRole.ADMIN.value,
        )
        db.add(admin)
        db.commit()
        print("✅ Default admin created: admin / admin123")
