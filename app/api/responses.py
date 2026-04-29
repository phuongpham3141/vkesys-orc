"""Consistent API response envelope helpers."""
from __future__ import annotations

from typing import Any, Optional

from flask import jsonify


def api_success(data: Any = None, meta: Optional[dict] = None, status: int = 200):
    return jsonify({"success": True, "data": data, "error": None, "meta": meta or {}}), status


def api_error(code: str, message: str, status: int = 400, *, details: Optional[dict] = None):
    payload = {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message},
    }
    if details:
        payload["error"]["details"] = details
    return jsonify(payload), status
