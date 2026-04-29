"""Google Cloud Document AI — Layout Parser adapter.

Layout Parser is a Document AI processor that performs OCR + structural
analysis (sections, headings, paragraphs, tables, lists) and returns layout
blocks with chunked text. It is dramatically more accurate than basic OCR on
forms, financial reports and tables.

Per-user configuration required (set in Settings -> Document AI tab):
    - GCP project id
    - location (e.g. ``us`` or ``eu``)
    - processor id (the Layout Parser processor created in Document AI console)
    - service account JSON (reused from Google Vision config)

The processor is documented at:
    https://cloud.google.com/document-ai/docs/layout-parse
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from flask import current_app

from .base import OCREngine, PageResult, ProgressCallback


class DocumentAILayoutOCR(OCREngine):
    """OCR via Document AI Layout Parser processor."""

    name = "document_ai"
    supports_native_pdf = True

    def _credentials_path(self, user_config) -> Optional[str]:
        if user_config is not None and getattr(user_config, "google_credentials_path", None):
            path = user_config.google_credentials_path
            if path and Path(path).exists():
                return path
        fallback = current_app.config.get("GOOGLE_APPLICATION_CREDENTIALS")
        if fallback and Path(fallback).exists():
            return fallback
        return None

    def _config_values(self, user_config) -> tuple[Optional[str], str, Optional[str]]:
        project = location = processor = None
        if user_config is not None:
            project = getattr(user_config, "documentai_project_id", None) or None
            location = getattr(user_config, "documentai_location", None) or None
            processor = getattr(user_config, "documentai_processor_id", None) or None
        location = location or "us"
        return project, location, processor

    def is_configured(self, user_config) -> bool:
        if not self._credentials_path(user_config):
            return False
        project, _, processor = self._config_values(user_config)
        return bool(project and processor)

    def _client(self, user_config, location: str):
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai

        cred_path = self._credentials_path(user_config)
        if cred_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        return documentai.DocumentProcessorServiceClient(client_options=opts)

    def _processor_name(self, project: str, location: str, processor_id: str) -> str:
        return f"projects/{project}/locations/{location}/processors/{processor_id}"

    def _process_bytes(self, raw_bytes: bytes, mime_type: str, user_config):
        from google.cloud import documentai

        project, location, processor_id = self._config_values(user_config)
        if not (project and processor_id):
            raise RuntimeError(
                "Document AI thieu cau hinh: project_id va processor_id la bat buoc"
            )

        client = self._client(user_config, location)
        request = documentai.ProcessRequest(
            name=self._processor_name(project, location, processor_id),
            raw_document=documentai.RawDocument(content=raw_bytes, mime_type=mime_type),
        )
        return client.process_document(request=request)

    def ocr_image(self, image_path: str, user_config) -> PageResult:
        with open(image_path, "rb") as fh:
            data = fh.read()
        suffix = Path(image_path).suffix.lstrip(".").lower() or "png"
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "tif": "image/tiff", "tiff": "image/tiff"}.get(suffix, "image/png")
        response = self._process_bytes(data, mime, user_config)
        text, raw, conf = self._extract_full(response)
        return PageResult(page_number=0, text=text, confidence=conf, raw_response=raw)

    def ocr_pdf(
        self,
        pdf_path: str,
        user_config,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> List[PageResult]:
        with open(pdf_path, "rb") as fh:
            data = fh.read()

        response = self._process_bytes(data, "application/pdf", user_config)
        document = response.document
        full_text = document.text or ""
        pages = list(document.pages or [])

        results: List[PageResult] = []
        total = len(pages) or 1
        for index, page in enumerate(pages, start=1):
            page_text = self._page_text(page, full_text)
            avg_conf = self._page_confidence(page)
            raw = {
                "engine": self.name,
                "page_number": index,
                "blocks": len(page.blocks),
                "tables": len(page.tables),
                "paragraphs": len(page.paragraphs),
                "form_fields": len(page.form_fields),
                "avg_confidence": avg_conf,
            }
            results.append(
                PageResult(
                    page_number=index,
                    text=page_text,
                    confidence=avg_conf,
                    raw_response=raw,
                )
            )
            if progress_callback is not None:
                progress_callback(index, total)

        if not results:
            results.append(
                PageResult(
                    page_number=1,
                    text=full_text,
                    raw_response={"engine": self.name, "fallback": "no pages"},
                )
            )
            if progress_callback is not None:
                progress_callback(1, 1)
        return results

    def _extract_full(self, response) -> tuple[str, dict, Optional[float]]:
        document = response.document
        text = document.text or ""
        confs = []
        for page in document.pages or []:
            for block in page.blocks or []:
                if block.layout and block.layout.confidence:
                    confs.append(float(block.layout.confidence))
        avg = sum(confs) / len(confs) if confs else None
        raw = {"engine": self.name, "pages": len(document.pages or []), "avg_confidence": avg}
        return text, raw, avg

    def _page_text(self, page, full_text: str) -> str:
        if not page.layout or not page.layout.text_anchor:
            return ""
        chunks = []
        for segment in page.layout.text_anchor.text_segments:
            start = int(segment.start_index) if segment.start_index else 0
            end = int(segment.end_index) if segment.end_index else 0
            chunks.append(full_text[start:end])
        return "".join(chunks)

    def _page_confidence(self, page) -> Optional[float]:
        confs = []
        for block in page.blocks or []:
            if block.layout and block.layout.confidence:
                confs.append(float(block.layout.confidence))
        if not confs:
            return None
        return sum(confs) / len(confs)
