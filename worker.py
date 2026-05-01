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


_BELOW_NORMAL = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
_DETACHED_PROCESS = 0x00000008  # subprocess detached, no console at all


def _spawn_runner(job_id: int, *, new_console: bool, logger: logging.Logger) -> subprocess.Popen | None:
    """Spawn ``run_one_job.py <job_id>`` as a separate process.

    Tries CREATE_NEW_CONSOLE first (visual feedback the user wanted), but
    Windows imposes a per-session desktop heap limit — once enough console
    windows are open, CreateProcess fails with ERROR_NOT_ENOUGH_MEMORY.
    On that error we fall back to a detached process that streams stdout
    + stderr into ``logs/jobs/job_<id>.log`` so the run still completes;
    the user can ``tail`` the log to watch progress.

    Each subprocess inherits a tiny DB pool (2 + 3) so 20 concurrent
    workers never hold more than 100 connections.
    """
    cmd = [sys.executable, str(ROOT / "run_one_job.py"), str(job_id)]
    env = os.environ.copy()
    env.setdefault("DB_POOL_SIZE", "2")
    env.setdefault("DB_MAX_OVERFLOW", "3")
    env.setdefault("VIC_NO_BOOTSTRAP", "1")
    # Tell the subprocess not to pause on input() if we're running detached
    # (no console = no stdin to read from).
    if not new_console:
        env["VIC_RUNNER_PAUSE"] = "0"

    if os.name == "nt" and new_console:
        flags = subprocess.CREATE_NEW_CONSOLE | _BELOW_NORMAL  # type: ignore[attr-defined]
        try:
            proc = subprocess.Popen(cmd, cwd=str(ROOT), creationflags=flags, env=env)
            logger.info(
                "Spawned runner for job %d (pid=%d, console=on)", job_id, proc.pid
            )
            return proc
        except OSError as exc:
            # ERROR_NOT_ENOUGH_MEMORY (8) when desktop heap is exhausted —
            # this is what kicks in around the 5th-10th simultaneous console
            # window on Windows Server. Fall through to detached spawn.
            logger.warning(
                "CREATE_NEW_CONSOLE failed for job %d (%s); retrying detached + log file",
                job_id, exc,
            )

    # Detached path — POSIX or Windows fallback / explicitly disabled
    log_path = ROOT / "logs" / "jobs" / f"job_{job_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_handle = open(log_path, "ab", buffering=0)
    except OSError:
        logger.exception("Could not open log file for job %d", job_id)
        return None

    flags = _BELOW_NORMAL if os.name == "nt" else 0
    if os.name == "nt":
        flags |= _DETACHED_PROCESS
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            creationflags=flags,
            env=env,
            stdout=log_handle,
            stderr=log_handle,
            stdin=subprocess.DEVNULL,
        )
        logger.info(
            "Spawned runner for job %d (pid=%d, detached, log=%s)",
            job_id, proc.pid, log_path,
        )
        return proc
    except Exception:
        log_handle.close()
        logger.exception("Failed to spawn runner for job %d (detached)", job_id)
        return None


def _fail_job(app, job_id: int, message: str, logger: logging.Logger) -> None:
    """Mark a claimed job as **failed** with an error message.

    Used when scheduler couldn't spawn a worker — keeping the job in
    ``processing`` would block a worker slot forever, and putting it back
    to ``pending`` would cause an infinite spawn-fail-retry loop. User
    can manually retry via the web UI.
    """
    from datetime import datetime as _dt

    with app.app_context():
        try:
            job = db.session.get(OCRJob, job_id)
            if job is not None and job.status in {"processing", "pending"}:
                job.status = "failed"
                job.error_message = message[:2000]
                job.completed_at = _dt.utcnow()
                job.runner_pid = None
                db.session.commit()
                logger.error("Job %d marked failed: %s", job_id, message)
        except Exception:
            db.session.rollback()
            logger.exception("Failed to mark job %d as failed", job_id)


def _sweep_stale_processing(app, logger: logging.Logger) -> int:
    """Reset jobs that are stuck in 'processing' but whose runner is gone.

    Runs once at scheduler startup. A job is considered abandoned when:
      - status='processing' AND
      - runner_pid is NULL, OR the OS process with that pid is no longer
        running on this host.
    Such jobs are reset to 'pending' so they get picked up again — safe
    because per-page incremental save means the runner will skip pages
    already in the DB.
    """
    import psutil  # type: ignore

    reset = 0
    with app.app_context():
        try:
            stuck = OCRJob.query.filter_by(status="processing").all()
        except Exception:
            db.session.rollback()
            logger.exception("Could not list processing jobs")
            return 0
        for job in stuck:
            pid = job.runner_pid
            alive = False
            if pid:
                try:
                    alive = psutil.pid_exists(int(pid))
                except Exception:
                    alive = False
            if not alive:
                job.status = "pending"
                job.runner_pid = None
                job.started_at = None
                reset += 1
        if reset:
            db.session.commit()
            logger.warning(
                "Sweep: reset %d stale 'processing' job(s) back to pending", reset
            )
    return reset


def _check_dead_handles(app, handles: list[subprocess.Popen], logger: logging.Logger) -> list[subprocess.Popen]:
    """Filter alive subprocesses + mark crashed-but-not-recorded jobs as failed.

    A subprocess that exits with a non-zero code WITHOUT updating its
    OCRJob row (e.g., import error before _run_job runs) leaves the job
    in 'processing' forever. After detecting the dead handle, we read
    the job back and if it's still in 'processing', mark failed.
    """
    alive = []
    for proc in handles:
        ret = proc.poll()
        if ret is None:
            alive.append(proc)
            continue
        # Subprocess has exited — if exit code was non-zero, check whether
        # the runner had time to update its job row before crashing.
        if ret != 0:
            with app.app_context():
                try:
                    job = (
                        db.session.query(OCRJob)
                        .filter(OCRJob.runner_pid == proc.pid)
                        .first()
                    )
                    if job is not None and job.status == "processing":
                        job.status = "failed"
                        job.error_message = (
                            f"Worker subprocess (pid={proc.pid}) "
                            f"exited with code {ret} before reporting status. "
                            f"Xem logs/jobs/job_{job.id}.log."
                        )
                        job.runner_pid = None
                        from datetime import datetime as _dt
                        job.completed_at = _dt.utcnow()
                        db.session.commit()
                        logger.error(
                            "Worker pid=%d crashed (exit %d); marked job %d failed",
                            proc.pid, ret, job.id,
                        )
                except Exception:
                    db.session.rollback()
                    logger.exception(
                        "Error inspecting crashed pid=%d", proc.pid
                    )
    return alive


def _alive(handles: list[subprocess.Popen]) -> list[subprocess.Popen]:
    """Filter list to subprocesses still running. Use _check_dead_handles
    when you also want to mark crashed jobs as failed."""
    return [p for p in handles if p.poll() is None]


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

    # On startup, recover any 'processing' jobs whose runner is no longer
    # alive (previous scheduler crash, host reboot, etc.). They're safe to
    # re-run thanks to per-page skip_pages.
    try:
        _sweep_stale_processing(app, logger)
    except Exception:
        logger.exception("Startup sweep crashed; continuing anyway")

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

            handles = _check_dead_handles(app, handles, logger)

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
                # Spawn failed even with detached fallback. Mark failed
                # (NOT pending) so we don't infinite-loop trying the same
                # bad job. User can retry manually from the web.
                _fail_job(
                    app,
                    job_id,
                    "Scheduler không thể spawn worker subprocess. "
                    "Có thể do hệ thống thiếu tài nguyên hoặc Windows "
                    "desktop heap đã đầy. Xem logs/scheduler.log.",
                    logger,
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
