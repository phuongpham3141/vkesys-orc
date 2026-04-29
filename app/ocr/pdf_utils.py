"""PDF helpers: rasterization and page counting."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

from flask import current_app


def get_page_count(pdf_path: str) -> int:
    """Return number of pages in a PDF."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    return len(reader.pages)


def pdf_to_images(pdf_path: str, dpi: int | None = None) -> List[Path]:
    """Convert a PDF into PNG images, one per page.

    Returns list of Paths to temporary PNG files. Caller is responsible for
    deleting them once OCR is finished.
    """
    from pdf2image import convert_from_path

    cfg_dpi = dpi or current_app.config.get("PDF_DPI", 200)
    poppler = current_app.config.get("POPPLER_PATH") or None

    out_dir = Path(tempfile.mkdtemp(prefix="vic_ocr_pages_"))
    images = convert_from_path(
        pdf_path,
        dpi=cfg_dpi,
        poppler_path=poppler,
        fmt="png",
        output_folder=str(out_dir),
        paths_only=True,
        thread_count=1,
    )
    return [Path(p) for p in images]
