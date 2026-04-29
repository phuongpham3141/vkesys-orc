"""Tesseract OCR adapter (local)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flask import current_app

from .base import OCREngine, PageResult


class TesseractOCR(OCREngine):
    """OCR via pytesseract with Vietnamese language data."""

    name = "tesseract"
    supports_native_pdf = False

    def _binary_path(self, user_config) -> Optional[str]:
        if user_config is not None and getattr(user_config, "tesseract_cmd_path", None):
            path = user_config.tesseract_cmd_path
            if path and Path(path).exists():
                return path
        fallback = current_app.config.get("TESSERACT_CMD")
        if fallback and Path(fallback).exists():
            return fallback
        return None

    def is_configured(self, user_config) -> bool:
        try:
            import pytesseract  # noqa: F401
        except Exception:
            return False
        return self._binary_path(user_config) is not None

    def ocr_image(self, image_path: str, user_config) -> PageResult:
        import pytesseract
        from PIL import Image

        binary = self._binary_path(user_config)
        if binary:
            pytesseract.pytesseract.tesseract_cmd = binary

        with Image.open(image_path) as img:
            text = pytesseract.image_to_string(img, lang="vie")

        raw = {"engine": self.name, "text_length": len(text)}
        return PageResult(page_number=0, text=text, raw_response=raw)
