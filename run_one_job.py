"""Run exactly one OCR job in this process, then exit.

Spawned by the scheduler (worker.py) — typically with
``CREATE_NEW_CONSOLE`` on Windows so the user can see live logs in a
dedicated console window.

Usage::

    python run_one_job.py <job_id>

Stdout/stderr is mirrored to ``logs/jobs/job_<id>.log`` for later review.
On Windows the console pauses at the end so the user has time to read
the result before it disappears.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Subprocess: skip create_app's bootstrap_admin / folder watcher / schema
# migration — the parent web process has already done all that.
os.environ.setdefault("VIC_NO_BOOTSTRAP", "1")


def _setup_logging(job_id: int) -> Path:
    log_dir = ROOT / "logs" / "jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"job_{job_id}.log"
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
    )
    file_h = RotatingFileHandler(
        path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_h.setFormatter(formatter)
    stream_h = logging.StreamHandler(sys.stdout)
    stream_h.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [file_h, stream_h]
    return path


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: run_one_job.py <job_id>", file=sys.stderr)
        return 2
    try:
        job_id = int(sys.argv[1])
    except ValueError:
        print(f"Invalid job_id: {sys.argv[1]!r}", file=sys.stderr)
        return 2

    log_path = _setup_logging(job_id)
    log = logging.getLogger("vic_ocr.run_one")
    log.info(
        "=== Job %d runner starting (pid=%d, log=%s) ===",
        job_id, os.getpid(), log_path,
    )

    try:
        from app import create_app
        from app.services.ocr_service import OCRService

        app = create_app()
        app.config["OCR_WORKER_MODE"] = "inprocess"
        service = OCRService()
        service.init_app(app)
        service.run_job_safe(job_id)
        log.info("=== Job %d runner finished cleanly ===", job_id)
        rc = 0
    except KeyboardInterrupt:
        log.warning("Job %d runner interrupted by user", job_id)
        rc = 130
    except Exception:
        log.exception("Job %d runner crashed", job_id)
        rc = 1

    if os.name == "nt" and os.getenv("VIC_RUNNER_PAUSE", "1") == "1":
        try:
            input("\n[Job done — press Enter to close window]")
        except (EOFError, KeyboardInterrupt):
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
