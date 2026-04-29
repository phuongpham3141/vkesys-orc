"""File storage helpers for uploaded PDFs and exported results."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Iterable

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


def upload_dir() -> Path:
    p = Path(current_app.config["UPLOAD_FOLDER"])
    p.mkdir(parents=True, exist_ok=True)
    return p


def output_dir() -> Path:
    p = Path(current_app.config["OUTPUT_FOLDER"])
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_uploaded_pdf(file_storage: FileStorage) -> tuple[str, str, int]:
    """Persist an uploaded PDF to disk under a UUID name.

    Returns ``(stored_filename, original_filename, size_bytes)``.
    """
    original = secure_filename(file_storage.filename or "upload.pdf")
    if not original.lower().endswith(".pdf"):
        original = f"{original}.pdf"
    stored = f"{uuid.uuid4().hex}.pdf"
    path = upload_dir() / stored
    file_storage.save(str(path))
    size = path.stat().st_size
    return stored, original, size


def stored_path(stored_filename: str) -> Path:
    return upload_dir() / stored_filename


def remove_stored_file(stored_filename: str) -> None:
    try:
        stored_path(stored_filename).unlink(missing_ok=True)
    except OSError:
        pass


def export_results_text(job, results: Iterable) -> Path:
    """Write plain-text export of all pages."""
    target = output_dir() / f"job_{job.id}.txt"
    with target.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(f"\n===== Trang {r.page_number} =====\n")
            fh.write(r.text_content or "")
            fh.write("\n")
    return target


def export_results_json(job, results: Iterable) -> Path:
    """Write structured JSON export."""
    target = output_dir() / f"job_{job.id}.json"
    payload = {
        "job_id": job.id,
        "filename": job.original_filename,
        "engine": job.engine,
        "page_count": job.page_count,
        "pages": [
            {
                "page_number": r.page_number,
                "text": r.text_content,
                "confidence": r.confidence_score,
            }
            for r in results
        ],
    }
    with target.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return target


def export_results_markdown(job, results: Iterable) -> Path:
    target = output_dir() / f"job_{job.id}.md"
    with target.open("w", encoding="utf-8") as fh:
        fh.write(f"# {job.original_filename}\n\n")
        fh.write(f"- Engine: `{job.engine}`\n")
        fh.write(f"- Số trang: {job.page_count}\n\n")
        for r in results:
            fh.write(f"\n## Trang {r.page_number}\n\n")
            fh.write(r.text_content or "")
            fh.write("\n")
    return target
