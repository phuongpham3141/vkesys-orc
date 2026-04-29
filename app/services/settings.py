"""DB-backed runtime settings with .env fallback.

Read priority:
    1. ``settings`` table row for the given key
    2. ``os.environ`` of the same name
    3. caller-supplied default

Use this for any value that admins should be able to change without an
app restart or shell access. Keys are stored uppercase by convention.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional

from ..extensions import db
from ..models import Setting


SETTING_DEFAULTS: dict[str, dict] = {
    "MAX_CONCURRENT_WORKERS": {
        "default": "2",
        "description": "So worker subprocess chay song song toi da (1-20).",
    },
    "DOCUMENT_AI_PAGES_PER_REQUEST": {
        "default": "1",
        "description": "Document AI: trang/request. 1 = an toan nhat, 30 = nhanh nhat.",
    },
    "WORKER_SPAWN_CONSOLE": {
        "default": "true",
        "description": "Co mo cua so console rieng cho moi job khong (Windows).",
    },
}


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        row = db.session.get(Setting, key)
    except Exception:
        db.session.rollback()
        row = None
    if row is not None and row.value is not None and row.value != "":
        return row.value
    env_val = os.getenv(key)
    if env_val is not None and env_val != "":
        return env_val
    if default is None:
        meta = SETTING_DEFAULTS.get(key)
        if meta is not None:
            return meta["default"]
    return default


def get_setting_int(key: str, default: int = 0, *, low: int = 0, high: int = 1_000_000) -> int:
    raw = get_setting(key, str(default))
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = default
    return max(low, min(high, v))


def get_setting_bool(key: str, default: bool = False) -> bool:
    raw = get_setting(key, str(default))
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def set_setting(key: str, value: Optional[str], description: Optional[str] = None) -> None:
    row = db.session.get(Setting, key)
    if row is None:
        row = Setting(key=key)
        db.session.add(row)
    row.value = "" if value is None else str(value)
    if description is not None:
        row.description = description
    elif row.description is None:
        meta = SETTING_DEFAULTS.get(key)
        if meta is not None:
            row.description = meta["description"]
    db.session.commit()


def list_settings(keys: Optional[Iterable[str]] = None) -> list[dict]:
    """Return a sorted snapshot for the admin UI.

    Each entry: ``{key, value, description, source}`` where source explains
    where the effective value came from (db / env / default).
    """
    target_keys = list(keys) if keys else sorted(SETTING_DEFAULTS.keys())
    rows = {r.key: r for r in Setting.query.filter(Setting.key.in_(target_keys)).all()}
    out = []
    for key in target_keys:
        meta = SETTING_DEFAULTS.get(key, {})
        row = rows.get(key)
        if row and row.value not in (None, ""):
            value, source = row.value, "db"
        elif os.getenv(key):
            value, source = os.getenv(key), "env"
        else:
            value, source = meta.get("default"), "default"
        out.append(
            {
                "key": key,
                "value": value,
                "description": meta.get("description") or (row.description if row else None),
                "source": source,
                "default": meta.get("default"),
            }
        )
    return out
