"""OCR engine factory."""
from __future__ import annotations

from typing import Dict, Type

from .base import OCREngine
from .google_vision import GoogleVisionOCR
from .mistral import MistralOCR
from .paddle import PaddleOCR
from .tesseract import TesseractOCR

ENGINES: Dict[str, Type[OCREngine]] = {
    "google_vision": GoogleVisionOCR,
    "mistral": MistralOCR,
    "paddle": PaddleOCR,
    "tesseract": TesseractOCR,
}


ENGINE_LABELS: Dict[str, dict] = {
    "google_vision": {"label": "Google Vision", "icon": "bi-google", "type": "Cloud"},
    "mistral": {"label": "Mistral OCR", "icon": "bi-cloud-lightning", "type": "Cloud"},
    "paddle": {"label": "PaddleOCR", "icon": "bi-cpu", "type": "Local"},
    "tesseract": {"label": "Tesseract", "icon": "bi-eye", "type": "Local"},
}


def get_engine(name: str) -> OCREngine:
    """Return an instance of the engine registered under ``name``."""
    if name not in ENGINES:
        raise ValueError(f"Unknown OCR engine: {name}")
    return ENGINES[name]()


def list_engine_names() -> list[str]:
    return list(ENGINES.keys())
