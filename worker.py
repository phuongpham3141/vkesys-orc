"""VIC OCR standalone worker.

Polls the database for pending OCR jobs and processes them serially in a
dedicated process. Run alongside the Flask web server so the web stays
responsive even while heavy OCR work is happening.

Usage::

    venv\\Scripts\\python.exe worker.py

Environment knobs:

    WORKER_POLL_INTERVAL   seconds between empty-queue polls (default 2)
    WORKER_REPORT_INTERVAL seconds between heartbeat reports (default 60)
    WORKER_LOG_LEVEL       INFO / DEBUG / WARNING (default INFO)

Stop with Ctrl+C — the worker drains the current job and exits cleanly.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import OCRJob  # noqa: E402
from app.services.ocr_service import OCRService  # noqa: E402


def _setup_logging() -> logging.Logger:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "worker.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(fmt)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)

    level_name = os.getenv("WORKER_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger = logging.getLogger("vic_ocr.worker")
    logger.setLevel(level)
    if not logger.handlers:
        logger.addHandler(handler)
        logger.addHandler(stream)
    logger.propagate = False
    return logger


_shutdown = False


def _request_shutdown(signum, frame):  # type: ignore[no-untyped-def]
    global _shutdown
    _shutdown = True


def _claim_next_job(app, logger) -> int | None:
    """Atomically pick a pending job and mark it processing.

    Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple workers running
    against the same database never grab the same job.
    """
    from sqlalchemy import text

    sql = text(
        """
        UPDATE ocr_jobs
           SET status = 'processing',
               started_at = COALESCE(started_at, NOW())
         WHERE id = (
             SELECT id FROM ocr_jobs
              WHERE status = 'pending'
              ORDER BY created_at ASC
              FOR UPDATE SKIP LOCKED
              LIMIT 1
         )
        RETURNING id
        """
    )
    with app.app_context():
        try:
            row = db.session.execute(sql).fetchone()
            db.session.commit()
            return int(row[0]) if row else None
        except Exception:
            db.session.rollback()
            logger.exception("Failed to claim next job")
            return None


def _queue_stats(app) -> dict:
    """Return a snapshot of job counts for the heartbeat report."""
    with app.app_context():
        out = {}
        for status in ("pending", "processing", "completed", "failed"):
            out[status] = OCRJob.query.filter_by(status=status).count()
        since = datetime.utcnow() - timedelta(hours=1)
        out["completed_last_hour"] = OCRJob.query.filter(
            OCRJob.status == "completed", OCRJob.completed_at >= since
        ).count()
        out["failed_last_hour"] = OCRJob.query.filter(
            OCRJob.status == "failed", OCRJob.completed_at >= since
        ).count()
        return out


def main() -> int:
    logger = _setup_logging()
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    app = create_app()
    # Force in-process mode for the OCRService used here so submit_job /
    # _run_job_safe actually run instead of being no-ops. The web app
    # uses its own OCRService instance with mode='external'.
    app.config["OCR_WORKER_MODE"] = "inprocess"
    service = OCRService()
    service.init_app(app)

    poll = max(1, int(os.getenv("WORKER_POLL_INTERVAL", "2")))
    report_every = max(10, int(os.getenv("WORKER_REPORT_INTERVAL", "60")))
    last_report = 0.0

    logger.info("Worker started (poll=%ds, report=%ds, pid=%d)", poll, report_every, os.getpid())
    logger.info("Database: %s", app.config.get("SQLALCHEMY_DATABASE_URI", "?").split("@")[-1])

    jobs_done = 0
    while not _shutdown:
        try:
            job_id = _claim_next_job(app, logger)
            if job_id is None:
                now = time.time()
                if now - last_report >= report_every:
                    stats = _queue_stats(app)
                    logger.info(
                        "Heartbeat: pending=%(pending)d processing=%(processing)d "
                        "completed=%(completed)d failed=%(failed)d "
                        "(last hour: ok=%(completed_last_hour)d fail=%(failed_last_hour)d) "
                        "done_this_session=%(session)d",
                        {**stats, "session": jobs_done},
                    )
                    last_report = now
                # cooperative shutdown: short sleeps so Ctrl+C is responsive
                for _ in range(poll):
                    if _shutdown:
                        break
                    time.sleep(1)
                continue

            t0 = time.time()
            logger.info("Claimed job %s, processing...", job_id)
            service.run_job_safe(job_id)
            elapsed = time.time() - t0
            jobs_done += 1
            logger.info("Job %s finished in %.1fs (session total: %d)", job_id, elapsed, jobs_done)
        except Exception:
            logger.exception("Worker loop iteration crashed; backing off")
            time.sleep(min(poll * 5, 30))

    logger.info("Worker shutting down (jobs done this session: %d)", jobs_done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
