"""Google Gemini multimodal OCR adapter.

Gemini accepts a PDF as inline data (or via the Files API for large docs)
and can produce a faithful, layout-aware Markdown transcription including
tables, headings and Vietnamese diacritics. For complex / structured
documents it often outperforms classical OCR engines.

Per-user configuration:
    - Gemini API key (encrypted in DB)
    - Optional Gemini model name (default ``gemini-2.5-pro`` — let user
      override to whatever model their project has access to, e.g.
      ``gemini-2.5-flash``, ``gemini-3.1-pro``, etc.)

The adapter sends the entire PDF in a single call and asks Gemini to emit
``=== Page N ===`` separators so we can split the response back into
per-page results matching the OCRResult schema.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from flask import current_app

from .base import OCREngine, PageResult, PageResultCallback, ProgressCallback

DEFAULT_MODEL = "gemini-2.5-pro"

PROMPT = """Bạn là OCR engine chuyên trích xuất văn bản từ tài liệu scan tiếng Việt.

Hãy đọc toàn bộ tài liệu PDF được đính kèm và trả về văn bản được trích xuất ở định dạng Markdown.

Yêu cầu:
1. Bảo toàn dấu tiếng Việt chính xác.
2. Giữ cấu trúc heading, bảng (Markdown table), danh sách.
3. Phân tách rõ ràng từng trang bằng dòng `===== Trang N =====` (N là số thứ tự trang, bắt đầu từ 1).
4. KHÔNG thêm bình luận, KHÔNG diễn giải, KHÔNG bao quanh kết quả bằng ```markdown blocks. Chỉ trả về văn bản đã trích xuất, được phân trang.
5. Nếu một trang có bảng, chuyển bảng đó sang Markdown table với đầy đủ các cột.
"""

PAGE_SEP_RE = re.compile(r"^\s*=+\s*Trang\s+(\d+)\s*=+\s*$", re.MULTILINE)


class GeminiOCR(OCREngine):
    """OCR via Google Gemini multimodal API."""

    name = "gemini"
    supports_native_pdf = True

    def _api_key(self, user_config) -> Optional[str]:
        if user_config is not None:
            key = getattr(user_config, "gemini_api_key", None)
            if key:
                return key
        return current_app.config.get("GEMINI_API_KEY") or None

    def _model_name(self, user_config) -> str:
        if user_config is not None:
            name = getattr(user_config, "gemini_model", None)
            if name:
                return name
        return current_app.config.get("GEMINI_MODEL") or DEFAULT_MODEL

    def is_configured(self, user_config) -> bool:
        return bool(self._api_key(user_config))

    def _model(self, user_config):
        import google.generativeai as genai

        genai.configure(api_key=self._api_key(user_config))
        return genai.GenerativeModel(self._model_name(user_config))

    def ocr_image(self, image_path: str, user_config) -> PageResult:
        from PIL import Image

        model = self._model(user_config)
        with Image.open(image_path) as img:
            response = model.generate_content([PROMPT, img])
        text = (response.text or "").strip()
        raw = {
            "engine": self.name,
            "model": self._model_name(user_config),
            "text_length": len(text),
        }
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
        with open(pdf_path, "rb") as fh:
            pdf_bytes = fh.read()

        model = self._model(user_config)
        if progress_callback is not None:
            progress_callback(0, 1)

        response = model.generate_content(
            [
                PROMPT,
                {"mime_type": "application/pdf", "data": pdf_bytes},
            ]
        )
        text = (response.text or "").strip()

        all_results = self._split_pages(text)
        if not all_results:
            all_results = [
                PageResult(
                    page_number=1,
                    text=text,
                    raw_response={
                        "engine": self.name,
                        "model": self._model_name(user_config),
                        "note": "no page separators detected",
                    },
                )
            ]
        else:
            for r in all_results:
                r.raw_response = {
                    "engine": self.name,
                    "model": self._model_name(user_config),
                    "text_length": len(r.text),
                }

        results: List[PageResult] = []
        for r in all_results:
            if r.page_number in skip:
                continue
            results.append(r)
            if on_page_result is not None:
                on_page_result(r)
        if progress_callback is not None:
            progress_callback(len(all_results), len(all_results))
        return results

    def _split_pages(self, text: str) -> List[PageResult]:
        if not text:
            return []
        matches = list(PAGE_SEP_RE.finditer(text))
        if not matches:
            return []
        results: List[PageResult] = []
        for idx, m in enumerate(matches):
            page_num = int(m.group(1))
            start = m.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            results.append(PageResult(page_number=page_num, text=content))
        return results
