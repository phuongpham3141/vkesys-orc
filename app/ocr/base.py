"""Abstract OCR engine interface and shared base behaviour."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional


@dataclass
class PageResult:
    """Single-page OCR output."""

    page_number: int
    text: str
    confidence: Optional[float] = None
    raw_response: Optional[dict] = field(default=None)


ProgressCallback = Callable[[int, int], None]


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
    ) -> List[PageResult]:
        """Default PDF processing: rasterize then OCR each page."""
        from .pdf_utils import pdf_to_images

        results: List[PageResult] = []
        image_paths = pdf_to_images(pdf_path)
        total = len(image_paths)
        try:
            for index, img_path in enumerate(image_paths, start=1):
                page_result = self.ocr_image(str(img_path), user_config)
                page_result.page_number = index
                results.append(page_result)
                if progress_callback is not None:
                    progress_callback(index, total)
        finally:
            for p in image_paths:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass
        return results
