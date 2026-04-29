"""Idempotent PostgreSQL bootstrap: creates database and required extensions.

Reads ``DATABASE_URL`` from ``.env`` (must be a ``postgresql+psycopg://`` URL),
connects to the ``postgres`` maintenance database, and:

  1. Creates the target database if it does not exist.
  2. Connects to the target database and creates the ``unaccent`` and
     ``pg_trgm`` extensions.

Designed to be safely re-run on every launcher start.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def main() -> int:
    raw_url = os.getenv("DATABASE_URL", "")
    if not raw_url:
        print("[init_db] DATABASE_URL chua duoc set trong .env", file=sys.stderr)
        return 1

    parsed_url = raw_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(parsed_url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        print(f"[init_db] DATABASE_URL khong phai PostgreSQL: {parsed.scheme}", file=sys.stderr)
        return 1

    target_db = (parsed.path or "/").lstrip("/") or "vic_ocr"
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    user = parsed.username or "postgres"
    password = parsed.password or ""

    try:
        import psycopg
    except ImportError:
        print("[init_db] psycopg chua duoc cai. Bo qua buoc nay.", file=sys.stderr)
        return 0

    try:
        with psycopg.connect(
            host=host, port=port, user=user, password=password, dbname="postgres",
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
                if cur.fetchone() is None:
                    cur.execute(f'CREATE DATABASE "{target_db}"')
                    print(f"[init_db] Da tao database '{target_db}'")
                else:
                    print(f"[init_db] Database '{target_db}' da ton tai")
    except Exception as exc:
        print(f"[init_db] Khong the ket noi PostgreSQL: {exc}", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(
            host=host, port=port, user=user, password=password, dbname=target_db,
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                print(f"[init_db] Da bat extensions unaccent, pg_trgm tren '{target_db}'")
    except Exception as exc:
        print(f"[init_db] Khong the bat extension: {exc}", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
