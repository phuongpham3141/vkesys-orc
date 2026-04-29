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
import logging
from pathlib import Path
from typing import Iterable, List, Optional, Set

from flask import current_app

from .base import OCREngine, PageResult, PageResultCallback, ProgressCallback

# Document AI sync ``processDocument`` accepts up to 30 pages per request,
# but we default to **1 page per request** so each page is its own atomic
# unit: failure of page N never invalidates pages 1..N-1, every page is
# saved to DB before the next API call, and "test single page" / resume
# semantics become trivial. Override via DOCUMENT_AI_PAGES_PER_REQUEST in
# .env if you want to trade resilience for a smaller bill of HTTPS overhead.
DEFAULT_PAGES_PER_REQUEST = 1
MAX_PAGES_PER_REQUEST = 30

logger = logging.getLogger(__name__)


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

    def _pages_per_request(self) -> int:
        try:
            n = int(
                current_app.config.get(
                    "DOCUMENT_AI_PAGES_PER_REQUEST", DEFAULT_PAGES_PER_REQUEST
                )
            )
        except (TypeError, ValueError):
            n = DEFAULT_PAGES_PER_REQUEST
        return max(1, min(MAX_PAGES_PER_REQUEST, n))

    def ocr_pdf(
        self,
        pdf_path: str,
        user_config,
        progress_callback: Optional[ProgressCallback] = None,
        on_page_result: Optional[PageResultCallback] = None,
        skip_pages: Optional[Iterable[int]] = None,
        target_pages: Optional[Iterable[int]] = None,
    ) -> List[PageResult]:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        if total_pages == 0:
            return []

        skip: Set[int] = set(skip_pages) if skip_pages else set()
        target: Optional[Set[int]] = set(target_pages) if target_pages else None
        chunk_size = self._pages_per_request()

        # Build the client once and reuse for every chunk — refreshing it
        # per-chunk previously caused intermittent 401s on long jobs.
        _, location, _ = self._config_values(user_config)
        client = self._client(user_config, location)
        logger.info(
            "DocumentAI ocr_pdf start: pdf=%s total_pages=%d chunk_size=%d "
            "skip=%d target=%s",
            Path(pdf_path).name, total_pages, chunk_size, len(skip),
            sorted(target) if target else "all",
        )

        results: List[PageResult] = []
        for chunk_start in range(0, total_pages, chunk_size):
            chunk_end = min(chunk_start + chunk_size, total_pages)
            chunk_pages = set(range(chunk_start + 1, chunk_end + 1))

            if target is not None and not (chunk_pages & target):
                if progress_callback is not None:
                    progress_callback(chunk_end, total_pages)
                continue
            if chunk_pages.issubset(skip):
                if progress_callback is not None:
                    progress_callback(chunk_end, total_pages)
                continue

            chunk_bytes = self._build_chunk(reader, chunk_start, chunk_end)
            try:
                response = self._process_bytes(
                    chunk_bytes, "application/pdf", user_config, client=client
                )
            except Exception:
                logger.exception(
                    "DocumentAI chunk failed (pages %d-%d)",
                    chunk_start + 1, chunk_end,
                )
                raise

            chunk_results = self._extract_pages(response, page_offset=chunk_start)
            logger.info(
                "DocumentAI chunk %d-%d returned %d page result(s)",
                chunk_start + 1, chunk_end, len(chunk_results),
            )
            for r in chunk_results:
                if r.page_number in skip:
                    continue
                if target is not None and r.page_number not in target:
                    continue
                results.append(r)
                if on_page_result is not None:
                    on_page_result(r)
            if progress_callback is not None:
                progress_callback(chunk_end, total_pages)

        if not results and not skip and target is None:
            logger.warning(
                "DocumentAI ocr_pdf returned 0 pages for PDF with %d pages",
                total_pages,
            )
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
        """Build per-page PageResults from a Document AI response.

        Layout Parser puts its hierarchical output in
        ``document.document_layout.blocks`` (each block has a page_span +
        text_block / table_block / list_block). The legacy OCR processor
        instead populates ``document.pages``. We support both, plus a
        full-text fallback.
        """
        document = response.document
        full_text = document.text or ""

        layout = getattr(document, "document_layout", None)
        layout_blocks = list(getattr(layout, "blocks", []) or []) if layout else []
        legacy_pages = list(document.pages or [])

        logger.info(
            "DocumentAI response shape: text_len=%d layout_blocks=%d legacy_pages=%d "
            "page_offset=%d",
            len(full_text), len(layout_blocks), len(legacy_pages), page_offset,
        )
        if logger.isEnabledFor(logging.DEBUG) and full_text:
            logger.debug("DocumentAI text preview: %r", full_text[:300])

        if layout_blocks:
            extracted = self._extract_from_layout(layout, page_offset)
            if extracted:
                return extracted
            logger.warning(
                "DocumentAI: document_layout had %d blocks but extractor produced 0 pages",
                len(layout_blocks),
            )

        if legacy_pages:
            extracted = self._extract_from_legacy_pages(legacy_pages, full_text, page_offset)
            if extracted:
                return extracted
            logger.warning(
                "DocumentAI: legacy pages[%d] but extractor produced 0 pages",
                len(legacy_pages),
            )

        if full_text:
            logger.info(
                "DocumentAI: falling back to single-page full-text result (%d chars)",
                len(full_text),
            )
            return [
                PageResult(
                    page_number=page_offset + 1,
                    text=full_text,
                    raw_response={
                        "engine": self.name,
                        "tables": [],
                        "note": "no structured layout, using document.text",
                    },
                )
            ]
        return []

    def _extract_from_legacy_pages(self, pages, full_text, page_offset):
        results: List[PageResult] = []
        for local_idx, page in enumerate(pages):
            global_page = page_offset + local_idx + 1
            page_text = self._page_text(page, full_text)
            avg_conf = self._page_confidence(page)
            tables = self._extract_legacy_tables(page, full_text)
            raw = {
                "engine": self.name,
                "page_number": global_page,
                "blocks": len(page.blocks),
                "tables": tables,
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

    def _extract_from_layout(self, layout, page_offset: int) -> List[PageResult]:
        """Parse the Layout Parser ``document_layout.blocks`` tree into per-page results."""
        per_page: dict[int, dict] = {}

        def _ensure(page_num: int) -> dict:
            if page_num not in per_page:
                per_page[page_num] = {"text_parts": [], "tables": []}
            return per_page[page_num]

        def _block_pages(block) -> list[int]:
            span = getattr(block, "page_span", None)
            if not span:
                return [1]
            start = int(getattr(span, "page_start", 0) or 1)
            end = int(getattr(span, "page_end", 0) or start)
            if end < start:
                end = start
            return list(range(start, end + 1))

        def _text_block_to_string(text_block) -> str:
            if text_block is None:
                return ""
            parts: list[str] = []
            if getattr(text_block, "text", None):
                parts.append(text_block.text)
            for nested in getattr(text_block, "blocks", []) or []:
                tb = getattr(nested, "text_block", None)
                if tb is not None:
                    parts.append(_text_block_to_string(tb))
            return "\n".join(p for p in parts if p)

        def _cell_to_string(cell) -> str:
            parts: list[str] = []
            for inner in getattr(cell, "blocks", []) or []:
                tb = getattr(inner, "text_block", None)
                if tb is not None:
                    s = _text_block_to_string(tb)
                    if s:
                        parts.append(s)
            return " ".join(parts).strip()

        def _table_to_rows(table_block) -> list[list[str]]:
            rows: list[list[str]] = []
            for row in list(getattr(table_block, "header_rows", []) or []) + list(
                getattr(table_block, "body_rows", []) or []
            ):
                cells: list[str] = []
                for cell in getattr(row, "cells", []) or []:
                    cells.append(_cell_to_string(cell))
                if cells:
                    rows.append(cells)
            return rows

        def _list_to_text(list_block) -> str:
            parts: list[str] = []
            for entry in getattr(list_block, "list_entries", []) or []:
                for child in getattr(entry, "blocks", []) or []:
                    tb = getattr(child, "text_block", None)
                    if tb is not None:
                        parts.append("- " + _text_block_to_string(tb))
            return "\n".join(parts)

        def _walk(block) -> None:
            text_block = getattr(block, "text_block", None)
            table_block = getattr(block, "table_block", None)
            list_block = getattr(block, "list_block", None)

            for page_num in _block_pages(block):
                bucket = _ensure(page_num)
                if text_block is not None and getattr(text_block, "text", None):
                    type_name = (getattr(text_block, "type_", "") or "").lower()
                    text = text_block.text
                    if "heading" in type_name:
                        text = "## " + text
                    bucket["text_parts"].append(text)
                if table_block is not None:
                    rows = _table_to_rows(table_block)
                    if rows:
                        bucket["tables"].append(rows)
                        # also include a Markdown rendering inline so plain
                        # TXT/MD downloads still show table content
                        bucket["text_parts"].append(self._rows_to_markdown(rows))
                if list_block is not None:
                    txt = _list_to_text(list_block)
                    if txt:
                        bucket["text_parts"].append(txt)

            # Recurse into nested children.
            if text_block is not None:
                for child in getattr(text_block, "blocks", []) or []:
                    _walk(child)

        for block in layout.blocks or []:
            _walk(block)

        results: List[PageResult] = []
        for local_page in sorted(per_page.keys()):
            data = per_page[local_page]
            global_page = page_offset + local_page
            results.append(
                PageResult(
                    page_number=global_page,
                    text="\n\n".join(p for p in data["text_parts"] if p).strip(),
                    raw_response={
                        "engine": self.name,
                        "page_number": global_page,
                        "tables": data["tables"],
                        "table_count": len(data["tables"]),
                        "source": "document_layout",
                    },
                )
            )
        return results

    def _extract_legacy_tables(self, page, full_text: str) -> list[list[list[str]]]:
        def _segment_text(anchor) -> str:
            if not anchor or not anchor.text_segments:
                return ""
            parts: list[str] = []
            for seg in anchor.text_segments:
                s = int(seg.start_index) if seg.start_index else 0
                e = int(seg.end_index) if seg.end_index else 0
                parts.append(full_text[s:e])
            return "".join(parts).strip()

        out: list[list[list[str]]] = []
        for tbl in getattr(page, "tables", []) or []:
            rows: list[list[str]] = []
            for row in list(getattr(tbl, "header_rows", []) or []) + list(
                getattr(tbl, "body_rows", []) or []
            ):
                cells = []
                for cell in getattr(row, "cells", []) or []:
                    cells.append(_segment_text(getattr(cell.layout, "text_anchor", None)))
                if cells:
                    rows.append(cells)
            if rows:
                out.append(rows)
        return out

    def _rows_to_markdown(self, rows: list[list[str]]) -> str:
        if not rows:
            return ""
        cols = max((len(r) for r in rows), default=0)
        if cols == 0:
            return ""
        lines: list[str] = []
        header = rows[0] + [""] * (cols - len(rows[0]))
        lines.append("| " + " | ".join(c.replace("\n", " ").replace("|", "\\|") for c in header) + " |")
        lines.append("|" + "|".join(["---"] * cols) + "|")
        for r in rows[1:]:
            r = r + [""] * (cols - len(r))
            lines.append("| " + " | ".join(c.replace("\n", " ").replace("|", "\\|") for c in r) + " |")
        return "\n".join(lines)

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
