import logging
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pathlib import Path

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import init_db, SessionLocal, get_db
from app.auth.auth_service import init_default_admin, decode_token, require_role
from app.models.user import User
from app.routes import auth_routes, staff_routes, attendance_routes
from app.scheduler import start_scheduler, stop_scheduler
from app.limiter import limiter
from sqlalchemy.orm import Session

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

try:
    _ = settings.SECRET_KEY
except RuntimeError as e:
    logger.critical(str(e))
    raise


def get_user_from_cookie(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    username = payload.get("sub")
    if not username:
        return None
    return db.query(User).filter(User.username == username, User.is_active == True).first()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Face Attendance System...")
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    init_db()
    db = SessionLocal()
    try:
        init_default_admin(db)
    finally:
        db.close()
    start_scheduler()
    logger.info(f"Shift defaults: {settings.SHIFT_START} - {settings.SHIFT_END}")
    logger.info(f"Face threshold: {settings.FACE_MATCH_THRESHOLD}")
    logger.info(f"Weekly off: {settings.DEFAULT_WEEKLY_OFF} (all hours = OT)")
    logger.info("System ready")
    yield
    stop_scheduler()
    logger.info("Face Attendance System stopped.")


app = FastAPI(
    title="Face Attendance System",
    description="Automated face-recognition attendance for housekeeping staff",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.include_router(auth_routes.router)
app.include_router(staff_routes.router)
app.include_router(attendance_routes.router)


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard")
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/staff")
def staff_page(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_cookie(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("staff.html", {"request": request})


@app.get("/muster")
def muster_page(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_cookie(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("muster.html", {"request": request})


@app.get("/punch")
def punch_page(request: Request):
    return templates.TemplateResponse("punch.html", {"request": request})


@app.get("/my-attendance")
def my_attendance_page(request: Request):
    return templates.TemplateResponse("my_attendance.html", {"request": request})


@app.get("/api/health")
def health():
    return {"status": "ok", "shift": f"{settings.SHIFT_START} - {settings.SHIFT_END}"}
