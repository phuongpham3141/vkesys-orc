"""VIC OCR watchdog — chay 1 lan, kiem tra suc khoe va tu khoi phuc.

Duoc Task Scheduler goi moi 15 phut. Kiem tra:
  1. Flask web (port 8000) co listen khong -> restart neu chet
  2. Scheduler heartbeat trong DB co fresh (<5 phut) khong -> restart neu stale
  3. Job 'processing' qua 30 phut ma runner_pid khong alive -> reset ve pending
  4. Job 'processing' qua 60 phut bat ke runner alive -> assume hung, kill + fail

Tat ca actions la idempotent — co the chay nhieu lan an toan.

Usage:
  venv\\Scripts\\python.exe scripts\\health_check.py [--dry-run]

Log ghi vao logs/health.log (RotatingFileHandler 5MB x 5).
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Add project to path if invoked standalone (not via venv)
sys.path.insert(0, str(ROOT))


def _setup_logging() -> logging.Logger:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "health.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
    )
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(handler.formatter)
    logger = logging.getLogger("vic_ocr.watchdog")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(handler)
        logger.addHandler(stream)
    logger.propagate = False
    return logger


def _read_env_db_url() -> str:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1]
    return os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:Phuong2606@localhost:5432/vic_ocr")


def _connect_db():
    """Lightweight psycopg connection — does NOT load Flask app."""
    import psycopg

    url = _read_env_db_url()
    # Strip SQLAlchemy dialect prefix
    pg_url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(pg_url, autocommit=True, connect_timeout=5)


def check_port_8000(logger: logging.Logger) -> bool:
    """True if Flask web is listening on port 8000."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", 8000))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def check_scheduler_heartbeat(conn, logger: logging.Logger) -> tuple[bool, int, int | None]:
    """Returns (is_fresh, age_seconds, scheduler_pid)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
          (SELECT value FROM settings WHERE key='LAST_SCHEDULER_HEARTBEAT'),
          (SELECT EXTRACT(EPOCH FROM (NOW() - updated_at))::int FROM settings WHERE key='LAST_SCHEDULER_HEARTBEAT'),
          (SELECT value FROM settings WHERE key='LAST_SCHEDULER_PID')
        """
    )
    row = cur.fetchone()
    if row is None or row[1] is None:
        return False, -1, None
    _hb_value, age_s, pid_value = row
    pid = None
    try:
        pid = int(pid_value) if pid_value else None
    except (TypeError, ValueError):
        pid = None
    is_fresh = age_s is not None and age_s < 300  # 5 min
    return is_fresh, age_s or 0, pid


def sweep_stuck_processing(conn, logger: logging.Logger, dry_run: bool) -> int:
    """Reset processing jobs whose runner_pid is dead OR running > 60 min."""
    import psutil

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, runner_pid,
               EXTRACT(EPOCH FROM (NOW() - started_at))::int AS runtime_s
          FROM ocr_jobs
         WHERE status = 'processing'
        """
    )
    rows = cur.fetchall()
    fixed = 0
    for job_id, runner_pid, runtime_s in rows:
        runtime_s = runtime_s or 0
        alive = False
        if runner_pid:
            try:
                alive = psutil.pid_exists(int(runner_pid))
            except Exception:
                alive = False

        # Case 1: runner gone, never finished — reset to pending
        if not alive:
            logger.warning(
                "Job %d processing %ds, runner_pid=%s not alive -> pending",
                job_id, runtime_s, runner_pid,
            )
            if not dry_run:
                cur.execute(
                    "UPDATE ocr_jobs SET status='pending', runner_pid=NULL,"
                    " started_at=NULL WHERE id=%s",
                    (job_id,),
                )
            fixed += 1
            continue

        # Case 2: runner still alive but ran > 60 min — assume hung, kill + fail
        if runtime_s > 3600:
            logger.error(
                "Job %d processing %ds (>60 min) with live pid=%d -> kill + fail",
                job_id, runtime_s, runner_pid,
            )
            if not dry_run:
                try:
                    psutil.Process(int(runner_pid)).kill()
                except Exception:
                    pass
                cur.execute(
                    "UPDATE ocr_jobs SET status='failed',"
                    " error_message=%s,"
                    " runner_pid=NULL,"
                    " completed_at=NOW() WHERE id=%s",
                    (
                        f"Watchdog killed runner pid={runner_pid} after "
                        f"{runtime_s//60} minutes (assumed hung).",
                        job_id,
                    ),
                )
            fixed += 1
    return fixed


def spawn_new_console(bat_path: Path, logger: logging.Logger) -> bool:
    """Spawn a .bat file in a new console window detached from watchdog."""
    if not bat_path.exists():
        logger.error("Bat file not found: %s", bat_path)
        return False
    try:
        # CREATE_NEW_CONSOLE | DETACHED — do NOT inherit handles from us
        flags = 0x00000010  # CREATE_NEW_CONSOLE
        subprocess.Popen(
            ["cmd", "/c", "start", "", str(bat_path)],
            cwd=str(ROOT),
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=False,
        )
        logger.info("Spawned %s in new console", bat_path.name)
        return True
    except Exception:
        logger.exception("Failed to spawn %s", bat_path.name)
        return False


def restart_flask(logger: logging.Logger, dry_run: bool) -> None:
    """Spawn start.bat (which also spawns scheduler)."""
    if dry_run:
        logger.info("[DRY-RUN] would spawn start.bat")
        return
    spawn_new_console(ROOT / "start.bat", logger)


def restart_scheduler(pid: int | None, logger: logging.Logger, dry_run: bool) -> None:
    """Kill stale scheduler PID then spawn a fresh worker.bat."""
    import psutil

    if pid:
        try:
            if psutil.pid_exists(pid):
                logger.warning("Killing stale scheduler pid=%d", pid)
                if not dry_run:
                    psutil.Process(pid).kill()
                    time.sleep(1)
        except Exception:
            logger.exception("Could not kill scheduler pid=%d", pid)
    if dry_run:
        logger.info("[DRY-RUN] would spawn worker.bat")
        return
    spawn_new_console(ROOT / "worker.bat", logger)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Log issues but don't take corrective action")
    args = parser.parse_args()

    logger = _setup_logging()
    logger.info("=== Health check start (dry_run=%s) ===", args.dry_run)

    # 1. Flask web
    if check_port_8000(logger):
        logger.info("Flask web: OK (port 8000 listening)")
    else:
        logger.error("Flask web: DOWN (port 8000 not listening) -> restart")
        restart_flask(logger, args.dry_run)
        # Allow Flask to come up before checking scheduler (start.bat also
        # spawns scheduler, so we may not need a separate restart)
        time.sleep(8)

    # 2. DB + scheduler heartbeat
    try:
        conn = _connect_db()
    except Exception:
        logger.exception("Could not connect to DB; skipping scheduler check")
        return 1

    try:
        is_fresh, age_s, sched_pid = check_scheduler_heartbeat(conn, logger)
        if is_fresh:
            logger.info("Scheduler: OK (heartbeat %ds ago, pid=%s)", age_s, sched_pid)
        else:
            logger.error(
                "Scheduler: STALE (heartbeat %ds ago, pid=%s) -> restart",
                age_s, sched_pid,
            )
            restart_scheduler(sched_pid, logger, args.dry_run)

        # 3. Stuck processing jobs
        fixed = sweep_stuck_processing(conn, logger, args.dry_run)
        if fixed:
            logger.warning("Reset/failed %d stuck processing job(s)", fixed)
        else:
            logger.info("No stuck processing jobs")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    logger.info("=== Health check done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
