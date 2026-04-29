"""Mistral OCR adapter (cloud API, supports native PDF)."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import List, Optional

from flask import current_app

from .base import OCREngine, PageResult, PageResultCallback, ProgressCallback


class MistralOCR(OCREngine):
    """OCR via Mistral's hosted ``mistral-ocr-latest`` model."""

    name = "mistral"
    supports_native_pdf = True
    model = "mistral-ocr-latest"

    def _api_key(self, user_config) -> Optional[str]:
        if user_config is not None:
            key = getattr(user_config, "mistral_api_key", None)
            if key:
                return key
        return current_app.config.get("MISTRAL_API_KEY") or None

    def is_configured(self, user_config) -> bool:
        return bool(self._api_key(user_config))

    def _client(self, user_config):
        from mistralai import Mistral

        return Mistral(api_key=self._api_key(user_config))

    def ocr_image(self, image_path: str, user_config) -> PageResult:
        client = self._client(user_config)
        with open(image_path, "rb") as fh:
            data = fh.read()
        b64 = base64.b64encode(data).decode("utf-8")
        suffix = Path(image_path).suffix.lstrip(".").lower() or "png"
        document = {"type": "image_url", "image_url": f"data:image/{suffix};base64,{b64}"}

        response = client.ocr.process(model=self.model, document=document)
        text, raw = self._extract(response)
        return PageResult(page_number=0, text=text, raw_response=raw)

    def ocr_pdf(
        self,
        pdf_path: str,
        user_config,
        progress_callback: Optional[ProgressCallback] = None,
        on_page_result: Optional[PageResultCallback] = None,
        skip_pages=None,
    ) -> List[PageResult]:
        skip = set(skip_pages) if skip_pages else set()
        client = self._client(user_config)
        with open(pdf_path, "rb") as fh:
            data = fh.read()
        b64 = base64.b64encode(data).decode("utf-8")
        document = {"type": "document_url", "document_url": f"data:application/pdf;base64,{b64}"}

        response = client.ocr.process(model=self.model, document=document)
        all_results = self._extract_per_page(response)

        results: List[PageResult] = []
        total = len(all_results) or 1
        for i, r in enumerate(all_results, start=1):
            if r.page_number in skip:
                if progress_callback is not None:
                    progress_callback(i, total)
                continue
            results.append(r)
            if on_page_result is not None:
                on_page_result(r)
            if progress_callback is not None:
                progress_callback(i, total)
        return results

    def _extract(self, response) -> tuple[str, dict]:
        pages = getattr(response, "pages", None) or []
        if pages:
            text = "\n\n".join(getattr(p, "markdown", "") or "" for p in pages)
        else:
            text = getattr(response, "text", "") or ""
        try:
            raw = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        except Exception:
            raw = {"engine": self.name, "note": "non-serializable response"}
        return text, raw

    def _extract_per_page(self, response) -> List[PageResult]:
        results: List[PageResult] = []
        pages = getattr(response, "pages", None) or []
        for index, page in enumerate(pages, start=1):
            md = getattr(page, "markdown", "") or ""
            try:
                raw = page.model_dump() if hasattr(page, "model_dump") else dict(page)
            except Exception:
                raw = {"engine": self.name, "page": index}
            results.append(PageResult(page_number=index, text=md, raw_response=raw))
        if not results:
            text, raw = self._extract(response)
            results.append(PageResult(page_number=1, text=text, raw_response=raw))
        return results
