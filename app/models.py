"""SQLAlchemy ORM models for VIC OCR.

Includes:
    - User: authentication + role
    - UserOCRConfig: per-user encrypted OCR engine credentials
    - OCRJob: a single PDF processing job
    - OCRResult: extracted text + raw response per page
"""
from __future__ import annotations

import secrets
from datetime import datetime
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from flask_login import UserMixin
from sqlalchemy import Index, text
from sqlalchemy.dialects.postgresql import JSONB
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def _fernet() -> Optional[Fernet]:
    """Return a Fernet instance built from ENCRYPTION_KEY config."""
    key = current_app.config.get("ENCRYPTION_KEY", "") if current_app else ""
    if not key:
        return None
    if isinstance(key, str):
        key = key.encode("utf-8")
    try:
        return Fernet(key)
    except Exception:  # pragma: no cover - bad key
        return None


def _encrypt(plaintext: Optional[str]) -> Optional[str]:
    if plaintext is None or plaintext == "":
        return None
    f = _fernet()
    if f is None:
        return plaintext  # fallback: store as-is, log warning
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _decrypt(ciphertext: Optional[str]) -> Optional[str]:
    if not ciphertext:
        return None
    f = _fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


class User(UserMixin, db.Model):
    """Application user with login credentials and role."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="user")
    api_token = db.Column(db.String(128), unique=True, nullable=True, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    oauth_provider = db.Column(db.String(32), nullable=True)
    oauth_uid = db.Column(db.String(128), nullable=True, index=True)
    avatar_url = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    ocr_config = db.relationship(
        "UserOCRConfig",
        backref="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    jobs = db.relationship(
        "OCRJob",
        backref="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def regenerate_api_token(self) -> str:
        self.api_token = secrets.token_urlsafe(48)
        return self.api_token

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username}>"


class UserOCRConfig(db.Model):
    """Per-user OCR engine credentials. Cloud API keys stored encrypted."""

    __tablename__ = "user_ocr_configs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    google_credentials_path = db.Column(db.String(512), nullable=True)
    mistral_api_key_encrypted = db.Column(db.Text, nullable=True)
    tesseract_cmd_path = db.Column(db.String(512), nullable=True)

    # Document AI Layout Parser
    documentai_project_id = db.Column(db.String(128), nullable=True)
    documentai_location = db.Column(db.String(32), nullable=True)
    documentai_processor_id = db.Column(db.String(128), nullable=True)

    # Gemini multimodal
    gemini_api_key_encrypted = db.Column(db.Text, nullable=True)
    gemini_model = db.Column(db.String(64), nullable=True)

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    @property
    def mistral_api_key(self) -> Optional[str]:
        return _decrypt(self.mistral_api_key_encrypted)

    @mistral_api_key.setter
    def mistral_api_key(self, value: Optional[str]) -> None:
        self.mistral_api_key_encrypted = _encrypt(value) if value else None

    @property
    def gemini_api_key(self) -> Optional[str]:
        return _decrypt(self.gemini_api_key_encrypted)

    @gemini_api_key.setter
    def gemini_api_key(self, value: Optional[str]) -> None:
        self.gemini_api_key_encrypted = _encrypt(value) if value else None


class OCRJob(db.Model):
    """A single OCR processing job (one PDF)."""

    __tablename__ = "ocr_jobs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename = db.Column(db.String(512), nullable=False)
    stored_filename = db.Column(db.String(512), nullable=False)
    file_size_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    page_count = db.Column(db.Integer, nullable=True)
    engine = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    source = db.Column(db.String(16), nullable=False, default="web")
    error_message = db.Column(db.Text, nullable=True)
    progress_percent = db.Column(db.Integer, nullable=False, default=0)
    target_pages = db.Column(JSONB, nullable=True)
    runner_pid = db.Column(db.Integer, nullable=True)
    # Optional override: when admin uploads on behalf of someone else, this
    # points at the user whose API keys / credentials should be billed.
    # NULL means use the job owner's own UserOCRConfig.
    key_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    results = db.relationship(
        "OCRResult",
        backref="job",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="OCRResult.page_number",
    )

    __table_args__ = (
        Index("ix_ocr_jobs_user_created", "user_id", "created_at"),
    )

    def to_dict(self, include_user: bool = False) -> dict:
        data = {
            "id": self.id,
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "file_size_bytes": self.file_size_bytes,
            "page_count": self.page_count,
            "engine": self.engine,
            "status": self.status,
            "source": self.source,
            "error_message": self.error_message,
            "progress_percent": self.progress_percent,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        if include_user and self.user is not None:
            data["user"] = {"id": self.user.id, "username": self.user.username}
        return data


class Setting(db.Model):
    """Simple key/value store for runtime-tunable application settings.

    Admin can edit values via /admin/settings without restarting the app
    or shell access to .env. Values are strings; helpers cast on read.
    """

    __tablename__ = "settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Setting {self.key}={self.value!r}>"


class OCRResult(db.Model):
    """Per-page OCR extraction result."""

    __tablename__ = "ocr_results"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer,
        db.ForeignKey("ocr_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number = db.Column(db.Integer, nullable=False)
    text_content = db.Column(db.Text, nullable=False, default="")
    raw_response = db.Column(JSONB, nullable=True)
    confidence_score = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index(
            "ix_ocr_results_text_trgm",
            text("text_content gin_trgm_ops"),
            postgresql_using="gin",
        ),
        Index(
            "ix_ocr_results_raw_jsonb",
            "raw_response",
            postgresql_using="gin",
        ),
        Index("ix_ocr_results_job_page", "job_id", "page_number", unique=True),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "page_number": self.page_number,
            "text_content": self.text_content,
            "confidence_score": self.confidence_score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
