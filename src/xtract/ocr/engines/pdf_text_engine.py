"""Engine for extracting born-digital embedded text layers from PDFs."""

from __future__ import annotations

import time

from xtract.ocr.engines.base import OcrEngine, OcrEngineUnavailable, OcrResult

MIN_CHARS_PER_PAGE = 25


def _load_pdfium():
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise OcrEngineUnavailable("pypdfium2 is not installed") from exc
    return pdfium


class PdfTextLayerEngine(OcrEngine):
    """Extracts the embedded text layer of born-digital PDFs."""

    name = "pdf_text"
    media_types = ("application/pdf",)

    def availability(self) -> tuple[bool, str]:
        try:
            _load_pdfium()
        except OcrEngineUnavailable as exc:
            return False, str(exc)
        return True, "available"

    def process(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        preprocess_steps: list[str] | None = None,
    ) -> OcrResult:
        pdfium = _load_pdfium()
        start = time.perf_counter()
        pdf = pdfium.PdfDocument(file_bytes)
        pages = []
        texts = []
        page_char_counts = []
        try:
            for page_index in range(len(pdf)):
                page = pdf[page_index]
                textpage = page.get_textpage()
                height = page.get_height()
                blocks = []
                for rect_index in range(textpage.count_rects()):
                    left, bottom, right, top = textpage.get_rect(rect_index)
                    segment = textpage.get_text_bounded(left, bottom, right, top).strip()
                    if not segment:
                        continue
                    blocks.append(
                        {
                            "block_id": f"p{page_index + 1}_block_{len(blocks) + 1:04d}",
                            "text": " ".join(segment.split()),
                            "confidence": 0.99,
                            "bounding_box": {
                                "left": round(left, 2),
                                "top": round(height - top, 2),
                                "width": round(right - left, 2),
                                "height": round(top - bottom, 2),
                            },
                        }
                    )
                page_text = textpage.get_text_range().replace("\r\n", "\n").strip()
                page_char_counts.append(len("".join(page_text.split())))
                texts.append(page_text)
                pages.append({"page_number": page_index + 1, "text_blocks": blocks})
                textpage.close()
                page.close()
        finally:
            pdf.close()

        # A text-rich page must not hide scanned pages elsewhere in a mixed PDF.
        has_text_layer = bool(page_char_counts) and all(
            count >= MIN_CHARS_PER_PAGE * 0.5 for count in page_char_counts
        )
        return OcrResult(
            engine_name=self.name,
            full_text="\n\n".join(texts).strip(),
            pages=pages,
            average_confidence=0.99 if has_text_layer else 0.0,
            duration_ms=int((time.perf_counter() - start) * 1000),
            note="Embedded text layer found." if has_text_layer else "No usable text layer.",
        )
