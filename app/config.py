"""
Application configuration - loaded from .env
All thresholds and timings are configurable here.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings:
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:123456@localhost:5432/Housekeep"
    )

    @property
    def db_connect_args(self):
        if "sqlite" in self.DATABASE_URL:
            return {"check_same_thread": False}
        return {}

    # JWT — SECRET_KEY is REQUIRED. Server will refuse to start without a real key.
    _SECRET_KEY_RAW: str = os.getenv("SECRET_KEY", "")
    _PLACEHOLDER_KEYS = {
        "",
        "change-me-in-production",
        "your-super-secret-key-change-in-production",
    }

    @property
    def SECRET_KEY(self) -> str:  # type: ignore[override]
        if self._SECRET_KEY_RAW in self._PLACEHOLDER_KEYS:
            raise RuntimeError(
                "\n\n[SECURITY] SECRET_KEY is not configured!\n"
                "  Set a secure random key in your .env file:\n"
                "    SECRET_KEY=<run: python -c \"import secrets; print(secrets.token_hex(32))\">\n"
                "  The server will NOT start without a real SECRET_KEY."
            )
        return self._SECRET_KEY_RAW

    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

    # Face Recognition
    FACE_MATCH_THRESHOLD: float = float(os.getenv("FACE_MATCH_THRESHOLD", "0.45"))
    ANTISPOOF_THRESHOLD: float = float(os.getenv("ANTISPOOF_THRESHOLD", "0.7"))
    LIVENESS_ENABLED: bool = os.getenv("LIVENESS_ENABLED", "true").lower() == "true"
    MIN_FACE_SIZE: int = int(os.getenv("MIN_FACE_SIZE", "80"))

    # Working Hours (7 AM to 4 PM, after 4 PM = OT)
    SHIFT_START: str = os.getenv("SHIFT_START", "07:00")
    SHIFT_END: str = os.getenv("SHIFT_END", "16:00")
    OT_RATE_MULTIPLIER: float = float(os.getenv("OT_RATE_MULTIPLIER", "1.5"))
    WORKING_DAYS_PER_WEEK: int = int(os.getenv("WORKING_DAYS_PER_WEEK", "6"))
    DEFAULT_WEEKLY_OFF: str = os.getenv("DEFAULT_WEEKLY_OFF", "Sunday")

    # System
    MAX_PUNCH_ATTEMPTS_PER_HOUR: int = int(os.getenv("MAX_PUNCH_ATTEMPTS_PER_HOUR", "6"))
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", str(BASE_DIR / "static" / "uploads" / "faces"))

    @staticmethod
    def ensure_dirs():
        """Create required directories (Windows-safe)."""
        import pathlib
        pathlib.Path(Settings.UPLOAD_DIR if hasattr(Settings, '_instance') else str(BASE_DIR / "static" / "uploads" / "faces")).mkdir(parents=True, exist_ok=True)
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Kolkata")


settings = Settings()
