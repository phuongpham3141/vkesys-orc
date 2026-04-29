"""Google Cloud Vision OCR adapter."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from flask import current_app

from .base import OCREngine, PageResult


class GoogleVisionOCR(OCREngine):
    """OCR via google-cloud-vision document_text_detection."""

    name = "google_vision"
    supports_native_pdf = False

    def _credentials_path(self, user_config) -> Optional[str]:
        if user_config is not None and getattr(user_config, "google_credentials_path", None):
            path = user_config.google_credentials_path
            if path and Path(path).exists():
                return path
        fallback = current_app.config.get("GOOGLE_APPLICATION_CREDENTIALS")
        if fallback and Path(fallback).exists():
            return fallback
        return None

    def is_configured(self, user_config) -> bool:
        return self._credentials_path(user_config) is not None

    def _client(self, user_config):
        from google.cloud import vision

        cred_path = self._credentials_path(user_config)
        if cred_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        return vision.ImageAnnotatorClient()

    def ocr_image(self, image_path: str, user_config) -> PageResult:
        from google.cloud import vision

        client = self._client(user_config)
        with open(image_path, "rb") as fh:
            content = fh.read()
        image = vision.Image(content=content)
        response = client.document_text_detection(
            image=image,
            image_context={"language_hints": ["vi", "en"]},
        )
        if response.error.message:
            raise RuntimeError(f"Google Vision error: {response.error.message}")

        full_text = response.full_text_annotation.text if response.full_text_annotation else ""

        confidence: Optional[float] = None
        if response.full_text_annotation and response.full_text_annotation.pages:
            confs = [
                p.confidence
                for p in response.full_text_annotation.pages
                if getattr(p, "confidence", None)
            ]
            if confs:
                confidence = sum(confs) / len(confs)

        raw = {
            "engine": self.name,
            "text_length": len(full_text),
            "confidence": confidence,
        }
        return PageResult(page_number=0, text=full_text, confidence=confidence, raw_response=raw)
