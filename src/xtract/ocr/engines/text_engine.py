"""Engine for decoding and reading born-digital plain text files."""

from __future__ import annotations

import time

from xtract.ocr.engines.base import OcrEngine, OcrResult, line_blocks


class PlainTextEngine(OcrEngine):
    """Reads born-digital plain text files without OCR."""

    name = "text"
    media_types = ("text/plain",)

    def process(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        preprocess_steps: list[str] | None = None,
    ) -> OcrResult:
        start = time.perf_counter()
        encoding = "utf-8"
        text = ""
        for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
            try:
                text = file_bytes.decode(enc)
                encoding = enc
                break
            except UnicodeDecodeError:
                continue
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return OcrResult(
            engine_name=self.name,
            full_text=text.strip(),
            pages=[{"page_number": 1, "text_blocks": line_blocks(text, 1.0)}],
            average_confidence=1.0 if text.strip() else 0.0,
            duration_ms=int((time.perf_counter() - start) * 1000),
            note=f"Decoded as {encoding}.",
        )
