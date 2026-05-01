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


def pdf_to_images(
    pdf_path: str,
    dpi: int | None = None,
    *,
    first_page: int | None = None,
    last_page: int | None = None,
) -> List[Path]:
    """Convert a PDF into PNG images, one per page.

    Pass ``first_page`` / ``last_page`` (1-indexed inclusive) to rasterize
    only a slice of the PDF. This is essential for engines that don't
    support native PDF input (Tesseract, Google Vision, PaddleOCR) so we
    don't dump 90 PNGs (~100MB) into %TEMP% before the first OCR call —
    that single Poppler burst was making the web feel sluggish during
    big jobs even though Flask itself was idle.

    Caller deletes the returned PNG paths.
    """
    from pdf2image import convert_from_path

    cfg_dpi = dpi or current_app.config.get("PDF_DPI", 200)
    poppler = current_app.config.get("POPPLER_PATH") or None

    out_dir = Path(tempfile.mkdtemp(prefix="vic_ocr_pages_"))
    kwargs = {
        "dpi": cfg_dpi,
        "poppler_path": poppler,
        "fmt": "png",
        "output_folder": str(out_dir),
        "paths_only": True,
        "thread_count": 1,
    }
    if first_page is not None:
        kwargs["first_page"] = first_page
    if last_page is not None:
        kwargs["last_page"] = last_page
    images = convert_from_path(pdf_path, **kwargs)
    return [Path(p) for p in images]
