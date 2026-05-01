"""Application configuration classes.

Loads values from environment variables (via python-dotenv). Provides separate
configurations for development and production deployments.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _abs(path: str) -> str:
    """Resolve a possibly-relative path to an absolute one anchored at BASE_DIR.

    Required because Flask 3's ``send_file`` resolves relative paths against
    ``app.root_path`` (which is ``app/``), not the project root, while
    ``Path.mkdir()`` etc. resolve against CWD — they would diverge.
    """
    if not path:
        return path
    p = Path(path)
    if not p.is_absolute():
        p = (BASE_DIR / p).resolve()
    return str(p)


class BaseConfig:
    """Shared configuration values."""

    # Flask
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-insecure-secret-change-me")
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "")

    # Database
    SQLALCHEMY_DATABASE_URI: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:Phuong2606@localhost:5432/vic_ocr",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Bigger pool so concurrent uploads + status polling + workers writing
    # results don't stall waiting for a free connection. Defaults of
    # pool_size=5 / max_overflow=10 caused the 'web is slow when 3-4 jobs
    # run' symptom because every status-poll request had to wait for one
    # of 15 connections to free up.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
    }
    # Static file cache (1 hour). galaxy.css / app.js etc. are served by
    # Flask in dev — caching avoids re-fetching on every page nav.
    SEND_FILE_MAX_AGE_DEFAULT = int(os.getenv("STATIC_CACHE_SECONDS", "3600"))

    # File storage (always stored as absolute paths)
    UPLOAD_FOLDER: str = _abs(os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "uploads")))
    OUTPUT_FOLDER: str = _abs(os.getenv("OUTPUT_FOLDER", str(BASE_DIR / "outputs")))
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024

    # OCR
    OCR_MAX_WORKERS: int = int(os.getenv("OCR_MAX_WORKERS", "2"))
    OCR_WORKER_MODE: str = os.getenv("OCR_WORKER_MODE", "external").lower()
    PDF_DPI: int = int(os.getenv("PDF_DPI", "200"))
    POPPLER_PATH: str = os.getenv("POPPLER_PATH", "")

    # Folder watcher
    FOLDER_WATCH_ENABLED: bool = _bool(os.getenv("FOLDER_WATCH_ENABLED"), False)
    WATCH_FOLDER_PATH: str = _abs(
        os.getenv("WATCH_FOLDER_PATH", str(BASE_DIR / "watch_folder"))
    )
    WATCH_FOLDER_PROCESSED_PATH: str = _abs(
        os.getenv("WATCH_FOLDER_PROCESSED_PATH", str(BASE_DIR / "watch_folder_processed"))
    )
    WATCH_FOLDER_USER_ID: int = int(os.getenv("WATCH_FOLDER_USER_ID", "1"))
    WATCH_FOLDER_ENGINE: str = os.getenv("WATCH_FOLDER_ENGINE", "tesseract")
    WATCH_INTERVAL_SECONDS: int = int(os.getenv("WATCH_INTERVAL_SECONDS", "30"))

    # Engine fallbacks
    # ALLOW_SYSTEM_FALLBACK_KEYS=true cho phép adapter fallback ve env vars
    # neu user khong co key rieng. Default false: moi user PHAI tu them key.
    ALLOW_SYSTEM_FALLBACK_KEYS: bool = _bool(
        os.getenv("ALLOW_SYSTEM_FALLBACK_KEYS"), False
    )
    GOOGLE_APPLICATION_CREDENTIALS: str = _abs(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    )
    MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "")
    TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")

    # Google OAuth (login with Google) — optional
    GOOGLE_OAUTH_CLIENT_ID: str = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    GOOGLE_OAUTH_CLIENT_SECRET: str = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    OAUTH_REDIRECT_URI: str = os.getenv("OAUTH_REDIRECT_URI", "")

    # Rate limiting
    API_RATE_LIMIT: str = os.getenv("API_RATE_LIMIT", "60/minute")

    # Session cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # SESSION_COOKIE_SECURE: True khi serve qua HTTPS (production behind
    # nginx/Cloudflare). Default false cho dev local. Override qua env.
    SESSION_COOKIE_SECURE: bool = _bool(os.getenv("SESSION_COOKIE_SECURE"), False)
    REMEMBER_COOKIE_HTTPONLY = True

    # OAuth state cần sống ít nhất 1 giờ (user có thể mất time ở Google).
    from datetime import timedelta as _td  # noqa: E402
    PERMANENT_SESSION_LIFETIME = _td(days=30)

    # WTForms
    WTF_CSRF_TIME_LIMIT = 7200


class DevConfig(BaseConfig):
    DEBUG = True
    TESTING = False


class ProdConfig(BaseConfig):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True


def get_config() -> type[BaseConfig]:
    """Return the configuration class based on FLASK_ENV."""
    env = os.getenv("FLASK_ENV", "development").lower()
    if env in {"production", "prod"}:
        return ProdConfig
    return DevConfig
