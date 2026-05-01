"""PaddleOCR adapter (local, supports Vietnamese)."""
from __future__ import annotations

import threading
from typing import Optional

from .base import OCREngine, PageResult


_paddle_lock = threading.Lock()
_paddle_instance = None


class PaddleOCR(OCREngine):
    """Local OCR via paddleocr.PaddleOCR with Vietnamese model."""

    name = "paddle"
    supports_native_pdf = False

    def is_configured(self, user_config) -> bool:
        # Cheap check: just verify the package is installed without importing
        # it. Importing paddleocr triggers loading of CV models (~3-5 seconds
        # cold) and was the dominant cause of slow page loads on /upload,
        # /settings and /jobs/<id> — every render iterated all 6 engines and
        # paddle's old import-based check froze the request.
        from importlib.util import find_spec
        try:
            return find_spec("paddleocr") is not None
        except (ImportError, ValueError):
            return False

    def _engine(self):
        global _paddle_instance
        if _paddle_instance is not None:
            return _paddle_instance
        with _paddle_lock:
            if _paddle_instance is None:
                from paddleocr import PaddleOCR as _PaddleOCR

                _paddle_instance = _PaddleOCR(
                    use_angle_cls=True,
                    lang="vi",
                    show_log=False,
                )
        return _paddle_instance

    def ocr_image(self, image_path: str, user_config) -> PageResult:
        engine = self._engine()
        result = engine.ocr(image_path, cls=True)

        lines: list[str] = []
        confs: list[float] = []
        if result and result[0]:
            for entry in result[0]:
                try:
                    _, (txt, conf) = entry
                except (ValueError, TypeError):
                    continue
                if txt:
                    lines.append(txt)
                if isinstance(conf, (int, float)):
                    confs.append(float(conf))

        avg_conf: Optional[float] = sum(confs) / len(confs) if confs else None
        raw = {
            "engine": self.name,
            "lines": len(lines),
            "avg_confidence": avg_conf,
        }
        return PageResult(
            page_number=0,
            text="\n".join(lines),
            confidence=avg_conf,
            raw_response=raw,
        )
