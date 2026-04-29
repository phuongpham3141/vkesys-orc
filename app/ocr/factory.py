"""OCR engine factory."""
from __future__ import annotations

from typing import Dict, Type

from .base import OCREngine
from .document_ai import DocumentAILayoutOCR
from .gemini import GeminiOCR
from .google_vision import GoogleVisionOCR
from .mistral import MistralOCR
from .paddle import PaddleOCR
from .tesseract import TesseractOCR

ENGINES: Dict[str, Type[OCREngine]] = {
    "google_vision": GoogleVisionOCR,
    "document_ai": DocumentAILayoutOCR,
    "gemini": GeminiOCR,
    "mistral": MistralOCR,
    "paddle": PaddleOCR,
    "tesseract": TesseractOCR,
}


ENGINE_LABELS: Dict[str, dict] = {
    "google_vision": {
        "label": "Google Vision",
        "icon": "bi-google",
        "type": "Cloud",
        "description": "OCR co ban tu Google Cloud Vision API",
    },
    "document_ai": {
        "label": "Document AI Layout",
        "icon": "bi-diagram-3",
        "type": "Cloud",
        "description": "Document AI Layout Parser - hieu cau truc tai lieu, bang, section",
    },
    "gemini": {
        "label": "Gemini Multimodal",
        "icon": "bi-stars",
        "type": "Cloud",
        "description": "Gemini API - OCR + hieu ngu nghia, giu cau truc bang phuc tap",
    },
    "mistral": {
        "label": "Mistral OCR",
        "icon": "bi-cloud-lightning",
        "type": "Cloud",
        "description": "Mistral OCR API - giu cau truc bang dang Markdown",
    },
    "paddle": {
        "label": "PaddleOCR",
        "icon": "bi-cpu",
        "type": "Local",
        "description": "PaddleOCR local, ho tro tieng Viet",
    },
    "tesseract": {
        "label": "Tesseract",
        "icon": "bi-eye",
        "type": "Local",
        "description": "Tesseract OCR local, mien phi, kha nang co ban",
    },
}


def get_engine(name: str) -> OCREngine:
    """Return an instance of the engine registered under ``name``."""
    if name not in ENGINES:
        raise ValueError(f"Unknown OCR engine: {name}")
    return ENGINES[name]()


def list_engine_names() -> list[str]:
    return list(ENGINES.keys())
