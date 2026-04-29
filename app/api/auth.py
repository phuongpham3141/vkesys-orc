"""API token authentication helper."""
from __future__ import annotations

from functools import wraps
from typing import Optional

from flask import g, request

from ..models import User
from .responses import api_error


def _extract_token() -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    api_key = request.headers.get("X-API-Token")
    return api_key.strip() if api_key else None


def token_required(view):
    """Reject requests that lack a valid API token."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        if not token:
            return api_error("UNAUTHORIZED", "Thiếu API token", 401)
        user = User.query.filter_by(api_token=token, is_active=True).first()
        if user is None:
            return api_error("INVALID_TOKEN", "Token không hợp lệ", 401)
        g.api_user = user
        return view(*args, **kwargs)

    return wrapper


def get_api_user() -> User:
    return g.api_user
