"""VIC OCR scheduler.

Polls the database for pending OCR jobs and **spawns one subprocess
(in its own console window on Windows) per job**, up to a configurable
concurrency limit. Each subprocess runs ``run_one_job.py <job_id>`` so
the user gets live, dedicated stdout for every job — easy to monitor
which engine is doing what and to spot errors as they happen.

Concurrency limit is read from the DB-backed setting
``MAX_CONCURRENT_WORKERS`` (clamped to ``[1, 20]``). Editable at
runtime from /admin/settings.

Stop with Ctrl+C — the scheduler stops accepting new pending jobs but
running subprocesses are left to finish on their own.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
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
from app.services.settings import get_setting_bool, get_setting_int, set_setting  # noqa: E402

WORKER_MIN = 1
WORKER_MAX = 20

_shutdown = False


def _request_shutdown(signum, frame):  # type: ignore[no-untyped-def]
    global _shutdown
    _shutdown = True


def _setup_logging() -> logging.Logger:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "scheduler.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s scheduler: %(message)s")
    handler.setFormatter(fmt)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger = logging.getLogger("vic_ocr.scheduler")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(handler)
        logger.addHandler(stream)
    logger.propagate = False
    return logger


def _claim_next_job(app, logger) -> int | None:
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


def _spawn_runner(job_id: int, *, new_console: bool, logger: logging.Logger) -> subprocess.Popen | None:
    """Spawn ``run_one_job.py <job_id>`` as a separate process.

    On Windows ``CREATE_NEW_CONSOLE`` opens a fresh cmd-style window so
    the user can watch this job's logs live; on POSIX or when
    new_console=False the subprocess runs detached and only writes to
    its log file.

    Each subprocess gets a TINY DB pool (2 + 3) — it only ever runs one
    OCR pipeline serially, so it does not need the web's big pool, and
    20 subprocesses inheriting Flask's pool_size=10 would grab 200+
    connections from PostgreSQL just sitting idle.
    """
    cmd = [sys.executable, str(ROOT / "run_one_job.py"), str(job_id)]
    creationflags = 0
    if os.name == "nt" and new_console:
        creationflags = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
    logger.info(
        "Spawning runner for job %d: console=%s cmd=%s flags=%#x",
        job_id, new_console, " ".join(cmd), creationflags,
    )
    env = os.environ.copy()
    env.setdefault("DB_POOL_SIZE", "2")
    env.setdefault("DB_MAX_OVERFLOW", "3")
    env.setdefault("VIC_NO_BOOTSTRAP", "1")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            creationflags=creationflags,
            env=env,
        )
        logger.info("Spawned runner for job %d (pid=%d)", job_id, proc.pid)
        return proc
    except Exception:
        logger.exception("Failed to spawn runner for job %d", job_id)
        return None


def _release_job(app, job_id: int, message: str, logger: logging.Logger) -> None:
    """Roll a claimed job back to pending if we couldn't actually launch."""
    with app.app_context():
        try:
            job = db.session.get(OCRJob, job_id)
            if job is not None and job.status == "processing":
                job.status = "pending"
                job.started_at = None
                job.error_message = message[:2000]
                db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Failed to release job %d back to pending", job_id)


def _alive(handles: list[subprocess.Popen]) -> list[subprocess.Popen]:
    """Filter list to subprocesses still running."""
    out = []
    for p in handles:
        if p.poll() is None:
            out.append(p)
    return out


def _queue_stats(app) -> dict:
    with app.app_context():
        out = {}
        for status in ("pending", "processing", "completed", "failed"):
            out[status] = OCRJob.query.filter_by(status=status).count()
        since = datetime.utcnow() - timedelta(hours=1)
        out["completed_last_hour"] = OCRJob.query.filter(
            OCRJob.status == "completed", OCRJob.completed_at >= since
        ).count()
        return out


def main() -> int:
    logger = _setup_logging()
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    app = create_app()
    poll = max(1, int(os.getenv("WORKER_POLL_INTERVAL", "2")))
    report_every = max(10, int(os.getenv("WORKER_REPORT_INTERVAL", "60")))

    logger.info(
        "Scheduler started (poll=%ds, pid=%d, runner=run_one_job.py)",
        poll, os.getpid(),
    )
    logger.info(
        "Database: %s", app.config.get("SQLALCHEMY_DATABASE_URI", "?").split("@")[-1]
    )

    handles: list[subprocess.Popen] = []
    spawned = 0
    last_report = 0.0

    while not _shutdown:
        try:
            with app.app_context():
                max_workers = get_setting_int(
                    "MAX_CONCURRENT_WORKERS", default=2, low=WORKER_MIN, high=WORKER_MAX
                )
                spawn_console = get_setting_bool("WORKER_SPAWN_CONSOLE", default=True)
                try:
                    set_setting(
                        "LAST_SCHEDULER_HEARTBEAT",
                        datetime.utcnow().isoformat(timespec="seconds"),
                    )
                    set_setting("LAST_SCHEDULER_PID", str(os.getpid()))
                except Exception:
                    db.session.rollback()

            handles = _alive(handles)

            if len(handles) >= max_workers:
                # Capacity full — wait without polling DB.
                time.sleep(poll)
                continue

            job_id = _claim_next_job(app, logger)
            if job_id is None:
                now = time.time()
                if now - last_report >= report_every:
                    stats = _queue_stats(app)
                    logger.info(
                        "Heartbeat: %s | running=%d/%d | spawned_session=%d",
                        " ".join(f"{k}={v}" for k, v in stats.items()),
                        len(handles), max_workers, spawned,
                    )
                    last_report = now
                for _ in range(poll):
                    if _shutdown:
                        break
                    time.sleep(1)
                continue

            proc = _spawn_runner(job_id, new_console=spawn_console, logger=logger)
            if proc is None:
                _release_job(
                    app, job_id, "Scheduler couldn't spawn runner", logger
                )
                time.sleep(poll)
                continue
            handles.append(proc)
            spawned += 1
            # Save PID so the web can kill it on Stop / Stop all.
            with app.app_context():
                try:
                    job_row = db.session.get(OCRJob, job_id)
                    if job_row is not None:
                        job_row.runner_pid = proc.pid
                        db.session.commit()
                except Exception:
                    db.session.rollback()
                    logger.exception("Failed to persist runner_pid for job %d", job_id)

        except Exception:
            logger.exception("Scheduler iteration crashed; backing off")
            time.sleep(min(poll * 5, 30))

    logger.info(
        "Scheduler shutting down (spawned this session: %d, still running: %d)",
        spawned, len(_alive(handles)),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
