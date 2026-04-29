"""OCR job orchestration via a thread pool."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime
from threading import Lock
from typing import Optional

from flask import Flask, current_app

from ..extensions import db
from ..models import OCRJob, OCRResult, UserOCRConfig
from ..ocr.factory import get_engine
from ..ocr.pdf_utils import get_page_count
from .storage import remove_stored_file, stored_path

logger = logging.getLogger(__name__)


class OCRService:
    """Owns OCR job orchestration.

    Two modes:

      - ``external`` (default): the Flask process only inserts the pending
        job row; ``submit_job()`` is a no-op. A separate ``worker.py``
        process polls the database and runs the OCR. This keeps the web
        responsive and avoids Werkzeug reloader / threading races.

      - ``inprocess``: legacy mode, uses an in-process
        ``ThreadPoolExecutor`` so ``submit_job()`` runs the OCR in a
        background thread of the web process. Useful for solo development
        when you don't want to launch a worker.
    """

    def __init__(self) -> None:
        self._executor: Optional[ThreadPoolExecutor] = None
        self._app: Optional[Flask] = None
        self._lock = Lock()
        self._mode: str = "external"

    def init_app(self, app: Flask) -> None:
        self._app = app
        self._mode = app.config.get("OCR_WORKER_MODE", "external")
        if self._mode == "inprocess":
            max_workers = int(app.config.get("OCR_MAX_WORKERS", 2))
            self._executor = ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix="ocr"
            )
            logger.info("OCRService init: in-process mode (%d workers)", max_workers)
        else:
            self._executor = None
            logger.info("OCRService init: external worker mode (run worker.py)")

    @property
    def mode(self) -> str:
        return self._mode

    def submit_job(self, job_id: int) -> Optional[Future]:
        if self._app is None:
            raise RuntimeError("OCRService not initialised. Call init_app() first.")
        if self._mode == "external":
            logger.info("Job %s queued (external worker will pick up)", job_id)
            return None
        if self._executor is None:
            raise RuntimeError("In-process executor not initialised")
        return self._executor.submit(self._run_job_safe, job_id)

    def run_job_safe(self, job_id: int) -> None:
        """Public wrapper used by the standalone worker."""
        self._run_job_safe(job_id)

    def _run_job_safe(self, job_id: int) -> None:
        assert self._app is not None
        with self._app.app_context():
            try:
                self._run_job(job_id)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Unhandled error processing job %s", job_id)

    def _run_job(self, job_id: int) -> None:
        job: Optional[OCRJob] = db.session.get(OCRJob, job_id)
        if job is None:
            logger.error("Job %s not found", job_id)
            return

        job.status = "processing"
        job.started_at = datetime.utcnow()
        job.progress_percent = 0
        db.session.commit()

        pdf_path = stored_path(job.stored_filename)
        if not pdf_path.exists():
            self._mark_failed(job, "File PDF không tồn tại trên đĩa.")
            return

        user_config: Optional[UserOCRConfig] = (
            UserOCRConfig.query.filter_by(user_id=job.user_id).first()
        )

        try:
            engine = get_engine(job.engine)
        except ValueError as exc:
            self._mark_failed(job, str(exc))
            return

        if not engine.is_configured(user_config):
            self._mark_failed(
                job,
                f"Engine '{job.engine}' chưa được cấu hình. Vui lòng vào Cài đặt để nhập credentials.",
            )
            return

        try:
            job.page_count = get_page_count(str(pdf_path))
        except Exception as exc:
            logger.warning("Cannot read page count: %s", exc)

        def progress_callback(current: int, total: int) -> None:
            try:
                pct = int((current / max(total, 1)) * 100)
                job_local = db.session.get(OCRJob, job_id)
                if job_local is not None:
                    job_local.progress_percent = pct
                    if job_local.page_count is None:
                        job_local.page_count = total
                    db.session.commit()
            except Exception:  # pragma: no cover - progress is best-effort
                db.session.rollback()

        # Pages already saved (e.g. from a partially-failed previous run)
        # are skipped so the user does not pay to re-OCR them.
        existing_pages = {
            row[0]
            for row in db.session.query(OCRResult.page_number)
            .filter_by(job_id=job_id)
            .all()
        }
        if existing_pages:
            logger.info(
                "Job %s: resuming, %d pages already saved",
                job_id,
                len(existing_pages),
            )

        def save_page(result) -> None:
            """Persist a single PageResult immediately (separate transaction)."""
            try:
                db.session.add(
                    OCRResult(
                        job_id=job_id,
                        page_number=result.page_number,
                        text_content=result.text or "",
                        confidence_score=result.confidence,
                        raw_response=result.raw_response,
                    )
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
                logger.exception(
                    "Job %s: failed to save page %s", job_id, result.page_number
                )

        target_pages = None
        if job.target_pages:
            try:
                target_pages = [int(p) for p in job.target_pages if p]
            except (TypeError, ValueError):
                target_pages = None

        try:
            new_results = engine.ocr_pdf(
                str(pdf_path),
                user_config,
                progress_callback=progress_callback,
                on_page_result=save_page,
                skip_pages=existing_pages,
                target_pages=target_pages,
            )
        except Exception as exc:
            logger.exception("OCR failed for job %s", job_id)
            self._mark_failed(job, f"OCR thất bại: {exc}")
            return

        # Engines that ignore on_page_result still return their full result
        # list; persist anything not already saved as a fallback path.
        already_saved = set(existing_pages)
        already_saved.update(
            row[0]
            for row in db.session.query(OCRResult.page_number)
            .filter_by(job_id=job_id)
            .all()
        )
        try:
            for r in new_results:
                if r.page_number in already_saved:
                    continue
                db.session.add(
                    OCRResult(
                        job_id=job.id,
                        page_number=r.page_number,
                        text_content=r.text or "",
                        confidence_score=r.confidence,
                        raw_response=r.raw_response,
                    )
                )
                already_saved.add(r.page_number)
            total_saved = (
                db.session.query(OCRResult).filter_by(job_id=job_id).count()
            )
            job.status = "completed"
            job.progress_percent = 100
            job.page_count = max(job.page_count or 0, total_saved)
            job.completed_at = datetime.utcnow()
            # Always clear target_pages so the next regular run processes the
            # whole document instead of just the test subset.
            job.target_pages = None
            job.runner_pid = None
            db.session.commit()
            logger.info(
                "Job %s completed with %d pages (target=%s)",
                job.id, total_saved, target_pages or "all"
            )
        except Exception as exc:
            db.session.rollback()
            logger.exception("Failed to persist results for job %s", job.id)
            self._mark_failed(job, f"Lỗi khi lưu kết quả: {exc}")

    def _mark_failed(self, job: OCRJob, message: str) -> None:
        job.status = "failed"
        job.error_message = message[:2000]
        job.completed_at = datetime.utcnow()
        job.runner_pid = None
        db.session.commit()
        logger.error("Job %s failed: %s", job.id, message)

    def delete_job_artifacts(self, job: OCRJob) -> None:
        if job.stored_filename:
            remove_stored_file(job.stored_filename)


_service: Optional[OCRService] = None
_service_lock = Lock()


def get_service() -> OCRService:
    """Return the lazily-initialised global OCR service for the current app."""
    global _service
    with _service_lock:
        if _service is None:
            _service = OCRService()
            _service.init_app(current_app._get_current_object())
        return _service
