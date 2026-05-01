"""Abstract OCR engine interface and shared base behaviour."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Set


@dataclass
class PageResult:
    """Single-page OCR output."""

    page_number: int
    text: str
    confidence: Optional[float] = None
    raw_response: Optional[dict] = field(default=None)


ProgressCallback = Callable[[int, int], None]
PageResultCallback = Callable[[PageResult], None]


class OCREngine(ABC):
    """Abstract base for all OCR engines."""

    name: str = "base"
    supports_native_pdf: bool = False  # True if engine can OCR a PDF directly (e.g. Mistral)

    @abstractmethod
    def is_configured(self, user_config) -> bool:
        """Return True when the engine has all required credentials."""

    @abstractmethod
    def ocr_image(self, image_path: str, user_config) -> PageResult:
        """OCR a single page image. Caller assigns the page number."""

    def ocr_pdf(
        self,
        pdf_path: str,
        user_config,
        progress_callback: Optional[ProgressCallback] = None,
        on_page_result: Optional[PageResultCallback] = None,
        skip_pages: Optional[Iterable[int]] = None,
        target_pages: Optional[Iterable[int]] = None,
    ) -> List[PageResult]:
        """Default PDF processing: rasterize **one page at a time** and OCR.

        Old behaviour rasterized every page upfront then looped — for a
        90-page PDF that meant Poppler's pdftoppm wrote ~100MB of PNGs
        into %TEMP% in a single 30-90 second burst, saturating one CPU
        core and the disk before the first OCR call ever happened.
        Now each iteration:

          1. extracts ONE page to a single PNG (pdf2image first/last_page)
          2. runs ocr_image on it
          3. invokes on_page_result so the result hits DB immediately
          4. deletes that PNG

        Net effect: disk usage at any moment is ~2MB instead of 100MB,
        Poppler's CPU spike is spread across the whole job, and Flask
        web stays responsive throughout.
        """
        from .pdf_utils import get_page_count, pdf_to_images

        skip: Set[int] = set(skip_pages) if skip_pages else set()
        target: Optional[Set[int]] = set(target_pages) if target_pages else None

        try:
            total = get_page_count(pdf_path)
        except Exception:
            total = 0

        results: List[PageResult] = []
        for index in range(1, total + 1):
            if target is not None and index not in target:
                if progress_callback is not None:
                    progress_callback(index, total)
                continue
            if index in skip:
                if progress_callback is not None:
                    progress_callback(index, total)
                continue

            page_pngs = pdf_to_images(pdf_path, first_page=index, last_page=index)
            if not page_pngs:
                if progress_callback is not None:
                    progress_callback(index, total)
                continue
            img_path = page_pngs[0]
            try:
                page_result = self.ocr_image(str(img_path), user_config)
                page_result.page_number = index
                results.append(page_result)
                if on_page_result is not None:
                    on_page_result(page_result)
            finally:
                try:
                    Path(img_path).unlink(missing_ok=True)
                except OSError:
                    pass
            if progress_callback is not None:
                progress_callback(index, total)
        return results
