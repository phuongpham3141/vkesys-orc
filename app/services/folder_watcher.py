"""Background folder watcher that auto-OCRs PDFs dropped in a directory."""
from __future__ import annotations

import logging
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask

from ..extensions import db
from ..models import OCRJob, User
from .ocr_service import get_service
from .storage import upload_dir

logger = logging.getLogger(__name__)

_watcher_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def _setup_logger(app: Flask) -> logging.Logger:
    log_dir = Path(app.root_path).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / "folder_watcher.log", encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
    )
    fw_logger = logging.getLogger("vic_ocr.folder_watcher")
    fw_logger.setLevel(logging.INFO)
    if not any(isinstance(h, logging.FileHandler) for h in fw_logger.handlers):
        fw_logger.addHandler(handler)
    return fw_logger


def start_watcher(app: Flask) -> None:
    """Spawn the watcher thread once."""
    global _watcher_thread
    if _watcher_thread and _watcher_thread.is_alive():
        return
    _stop_event.clear()
    _watcher_thread = threading.Thread(
        target=_run, args=(app,), name="folder-watcher", daemon=True
    )
    _watcher_thread.start()
    app.logger.info("Folder watcher thread started")


def stop_watcher() -> None:
    _stop_event.set()


def _run(app: Flask) -> None:
    fw_logger = _setup_logger(app)
    interval = int(app.config.get("WATCH_INTERVAL_SECONDS", 30))
    while not _stop_event.is_set():
        try:
            with app.app_context():
                _scan_once(app, fw_logger)
        except Exception:
            fw_logger.exception("Watcher iteration failed")
        _stop_event.wait(interval)


def _scan_once(app: Flask, fw_logger: logging.Logger) -> None:
    src = Path(app.config["WATCH_FOLDER_PATH"])
    dst = Path(app.config["WATCH_FOLDER_PROCESSED_PATH"])
    src.mkdir(parents=True, exist_ok=True)
    dst.mkdir(parents=True, exist_ok=True)

    user_id = int(app.config.get("WATCH_FOLDER_USER_ID", 1))
    engine = app.config.get("WATCH_FOLDER_ENGINE", "tesseract")

    user = db.session.get(User, user_id)
    if user is None:
        fw_logger.warning("Watcher user_id %s not found, skipping", user_id)
        return

    for pdf in sorted(src.glob("*.pdf")):
        try:
            stored_name = f"{int(time.time() * 1000)}_{pdf.name}"
            target = upload_dir() / stored_name
            shutil.copy2(pdf, target)
            size = target.stat().st_size

            job = OCRJob(
                user_id=user.id,
                original_filename=pdf.name,
                stored_filename=stored_name,
                file_size_bytes=size,
                engine=engine,
                status="pending",
                source="folder_watch",
                created_at=datetime.utcnow(),
            )
            db.session.add(job)
            db.session.commit()
            fw_logger.info("Created job %s from %s", job.id, pdf.name)

            get_service().submit_job(job.id)

            processed_name = pdf.name
            if (dst / processed_name).exists():
                processed_name = f"{int(time.time())}_{pdf.name}"
            shutil.move(str(pdf), str(dst / processed_name))
            fw_logger.info("Moved %s -> %s", pdf.name, dst / processed_name)
        except Exception:
            fw_logger.exception("Failed to enqueue %s", pdf)
            db.session.rollback()
