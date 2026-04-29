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

import io
from pathlib import Path
from typing import Iterable, List, Optional, Set

from flask import current_app

from .base import OCREngine, PageResult, PageResultCallback, ProgressCallback

# Document AI sync ``processDocument`` rejects payloads >30 pages with
# PAGE_LIMIT_EXCEEDED. We chunk the PDF and process each slice serially.
MAX_PAGES_PER_REQUEST = 30


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
        """Build a Document AI client with explicit Service Account credentials.

        Avoids relying on the ``GOOGLE_APPLICATION_CREDENTIALS`` env var, which
        is process-global state and can be flaky across long-running calls
        (we previously saw chunk 2 of a 90-page job failing with
        CREDENTIALS_MISSING after chunk 1 succeeded).
        """
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai
        from google.oauth2 import service_account

        cred_path = self._credentials_path(user_config)
        if not cred_path:
            raise RuntimeError(
                "Document AI cần Service Account JSON. "
                "Vào Cài đặt → Google Vision để upload."
            )
        creds = service_account.Credentials.from_service_account_file(cred_path)
        opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        return documentai.DocumentProcessorServiceClient(
            credentials=creds, client_options=opts
        )

    def _processor_name(self, project: str, location: str, processor_id: str) -> str:
        return f"projects/{project}/locations/{location}/processors/{processor_id}"

    def _process_bytes(self, raw_bytes: bytes, mime_type: str, user_config, client=None):
        from google.api_core.exceptions import (
            FailedPrecondition,
            NotFound,
            PermissionDenied,
        )
        from google.cloud import documentai

        project, location, processor_id = self._config_values(user_config)
        if not (project and processor_id):
            raise RuntimeError(
                "Document AI thiếu cấu hình: cần Project ID và Processor ID. "
                "Vào Cài đặt → tab Document AI Layout."
            )

        if client is None:
            client = self._client(user_config, location)
        request = documentai.ProcessRequest(
            name=self._processor_name(project, location, processor_id),
            raw_document=documentai.RawDocument(content=raw_bytes, mime_type=mime_type),
        )
        try:
            return client.process_document(request=request)
        except PermissionDenied as exc:
            raise RuntimeError(
                f"Document AI từ chối truy cập project '{project}'. "
                f"Hãy kiểm tra:\n"
                f"  1) Project ID đã đúng chưa (Project NAME ≠ Project ID — "
                f"Project ID thường có suffix random, vd: '{project}-475822')\n"
                f"  2) Đã bật Document AI API trên project chưa\n"
                f"  3) Project đã link với Billing Account chưa\n"
                f"  4) Service Account có role 'Document AI API User'\n"
                f"Chạy `venv\\Scripts\\python.exe scripts\\verify_gcp.py` để chẩn đoán.\n"
                f"Chi tiết: {exc}"
            ) from exc
        except NotFound as exc:
            raise RuntimeError(
                f"Không tìm thấy Processor '{processor_id}' trong "
                f"project '{project}', location '{location}'. "
                f"Kiểm tra Processor ID + region trong Document AI Console."
            ) from exc
        except FailedPrecondition as exc:
            raise RuntimeError(
                f"Document AI: tiền điều kiện không thoả (thường do API "
                f"chưa bật hoặc billing chưa link). Chi tiết: {exc}"
            ) from exc

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
        on_page_result: Optional[PageResultCallback] = None,
        skip_pages: Optional[Iterable[int]] = None,
    ) -> List[PageResult]:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        if total_pages == 0:
            return []

        skip: Set[int] = set(skip_pages) if skip_pages else set()

        # Build the client once and reuse for every chunk — refreshing it
        # per-chunk previously caused intermittent 401s on long jobs.
        _, location, _ = self._config_values(user_config)
        client = self._client(user_config, location)

        results: List[PageResult] = []
        for chunk_start in range(0, total_pages, MAX_PAGES_PER_REQUEST):
            chunk_end = min(chunk_start + MAX_PAGES_PER_REQUEST, total_pages)

            # Skip a chunk only when EVERY page in its range is already saved.
            chunk_pages = set(range(chunk_start + 1, chunk_end + 1))
            if chunk_pages.issubset(skip):
                if progress_callback is not None:
                    progress_callback(chunk_end, total_pages)
                continue

            chunk_bytes = self._build_chunk(reader, chunk_start, chunk_end)
            response = self._process_bytes(
                chunk_bytes, "application/pdf", user_config, client=client
            )
            chunk_results = self._extract_pages(response, page_offset=chunk_start)
            for r in chunk_results:
                if r.page_number in skip:
                    continue
                results.append(r)
                if on_page_result is not None:
                    on_page_result(r)
            if progress_callback is not None:
                progress_callback(chunk_end, total_pages)

        if not results and not skip:
            results.append(
                PageResult(
                    page_number=1,
                    text="",
                    raw_response={
                        "engine": self.name,
                        "fallback": "no pages returned by any chunk",
                        "total_pages": total_pages,
                    },
                )
            )
        return results

    def _build_chunk(self, reader, start: int, end: int) -> bytes:
        """Return PDF bytes containing only pages ``[start, end)`` of ``reader``."""
        from pypdf import PdfWriter

        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    def _extract_pages(self, response, page_offset: int) -> List[PageResult]:
        document = response.document
        full_text = document.text or ""
        results: List[PageResult] = []
        for local_idx, page in enumerate(document.pages or []):
            global_page = page_offset + local_idx + 1
            page_text = self._page_text(page, full_text)
            avg_conf = self._page_confidence(page)
            raw = {
                "engine": self.name,
                "page_number": global_page,
                "blocks": len(page.blocks),
                "tables": len(page.tables),
                "paragraphs": len(page.paragraphs),
                "form_fields": len(page.form_fields),
                "avg_confidence": avg_conf,
            }
            results.append(
                PageResult(
                    page_number=global_page,
                    text=page_text,
                    confidence=avg_conf,
                    raw_response=raw,
                )
            )
        return results

    def _empty_fallback(self, response) -> List[PageResult]:
        document = response.document
        return [
            PageResult(
                page_number=1,
                text=document.text or "",
                raw_response={"engine": self.name, "fallback": "no pages"},
            )
        ]

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
