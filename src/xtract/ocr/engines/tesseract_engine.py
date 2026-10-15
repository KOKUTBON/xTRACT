"""Tesseract OCR engine with resource exhaustion guards, deadlines, and DPI limits."""

from __future__ import annotations

import io
import math
import os
import shutil
import time

from xtract.ocr.engines.base import OcrEngine, OcrEngineUnavailable, OcrResult

PDF_RENDER_DPI = 300
MAX_PAGE_DIMENSION = 5000  # maximum width/height in points
MAX_PAGE_PIXELS = 25_000_000  # 25 MP per page maximum
MAX_TOTAL_PIXELS = 100_000_000  # 100 MP per document total
DEFAULT_PAGE_TIMEOUT = 30.0
DEFAULT_TOTAL_TIMEOUT = 120.0


def _load_dependencies():
    try:
        import pytesseract
        from PIL import Image, ImageOps

        # Protect against decompression bomb denial-of-service
        Image.MAX_IMAGE_PIXELS = MAX_PAGE_PIXELS * 2
    except ImportError as exc:
        raise OcrEngineUnavailable("pytesseract and Pillow are not installed") from exc
    return pytesseract, Image, ImageOps


class TesseractOcrEngine(OcrEngine):
    """Tesseract OCR for images and scanned PDFs with strict resource limits."""

    name = "tesseract"
    media_types = ("image/*", "application/pdf")

    def __init__(
        self,
        languages: str | None = None,
        max_pages: int = 50,
        page_timeout: float = DEFAULT_PAGE_TIMEOUT,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
    ) -> None:
        self.languages = languages or os.environ.get("XTRACT_TESSERACT_LANG", "eng")
        self.max_pages = max_pages
        self.page_timeout = float(os.environ.get("XTRACT_OCR_PAGE_TIMEOUT", page_timeout))
        self.total_timeout = float(os.environ.get("XTRACT_OCR_TOTAL_TIMEOUT", total_timeout))

    def availability(self) -> tuple[bool, str]:
        try:
            pytesseract, _, _ = _load_dependencies()
        except OcrEngineUnavailable as exc:
            return False, str(exc)
        command = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
        if not shutil.which(command) and not os.path.isfile(command):
            return False, "the tesseract executable is not on PATH"
        return True, "available"

    def _images(self, file_bytes: bytes, mime_type: str, image_module):
        total_rendered_pixels = 0

        if mime_type == "application/pdf":
            try:
                import pypdfium2 as pdfium
            except ImportError as exc:
                raise OcrEngineUnavailable("pypdfium2 is required to OCR PDF files") from exc
            pdf = pdfium.PdfDocument(file_bytes)
            try:
                if len(pdf) > self.max_pages:
                    raise ValueError(
                        f"PDF exceeds the {self.max_pages}-page OCR limit; split it before uploading."
                    )
                for index in range(len(pdf)):
                    page = pdf[index]
                    width = page.get_width()
                    height = page.get_height()

                    if width > MAX_PAGE_DIMENSION or height > MAX_PAGE_DIMENSION:
                        raise ValueError(
                            f"Page {index + 1} dimensions ({width}x{height} pt) exceed safe limit ({MAX_PAGE_DIMENSION} pt)."
                        )

                    scale = PDF_RENDER_DPI / 72.0
                    projected_pixels = (width * scale) * (height * scale)
                    if projected_pixels > MAX_PAGE_PIXELS:
                        # Clamp scale to prevent memory exhaustion
                        scale = math.sqrt(MAX_PAGE_PIXELS / (width * height))

                    page_pixels = int((width * scale) * (height * scale))
                    total_rendered_pixels += page_pixels
                    if total_rendered_pixels > MAX_TOTAL_PIXELS:
                        raise ValueError(
                            f"Document exceeds maximum total rendered pixels limit ({MAX_TOTAL_PIXELS})."
                        )

                    pil_image = page.render(scale=scale).to_pil()
                    page.close()
                    yield pil_image
            finally:
                pdf.close()
            return

        image = image_module.open(io.BytesIO(file_bytes))
        num_frames = getattr(image, "n_frames", 1)
        if num_frames > self.max_pages:
            image.close()
            raise ValueError(
                f"Image exceeds the {self.max_pages}-frame OCR limit; split it before uploading."
            )
        frame = 0
        while True:
            current_pixels = image.width * image.height
            if current_pixels > MAX_PAGE_PIXELS:
                image.close()
                raise ValueError(
                    f"Image frame {frame + 1} exceeds maximum page pixel limit ({MAX_PAGE_PIXELS})."
                )
            total_rendered_pixels += current_pixels
            if total_rendered_pixels > MAX_TOTAL_PIXELS:
                image.close()
                raise ValueError(f"Image exceeds total rendered pixel limit ({MAX_TOTAL_PIXELS}).")
            yield image.copy()
            frame += 1
            try:
                image.seek(frame)
            except EOFError:
                break
        image.close()

    def process(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        preprocess_steps: list[str] | None = None,
    ) -> OcrResult:
        ok, reason = self.availability()
        if not ok:
            raise OcrEngineUnavailable(reason)
        pytesseract, image_module, image_ops = _load_dependencies()
        steps = set(preprocess_steps or [])
        start = time.perf_counter()
        pages, texts, confidences = [], [], []

        for page_number, image in enumerate(self._images(file_bytes, mime_type, image_module), 1):
            elapsed = time.perf_counter() - start
            if elapsed >= self.total_timeout:
                raise TimeoutError(
                    f"OCR processing timed out after {self.total_timeout}s at page {page_number}."
                )

            remaining_timeout = max(
                1, min(int(self.page_timeout), int(self.total_timeout - elapsed))
            )

            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            if "grayscale" in steps:
                image = image_ops.grayscale(image)
            if "autocontrast" in steps:
                image = image_ops.autocontrast(image)

            data = pytesseract.image_to_data(
                image,
                lang=self.languages,
                output_type=pytesseract.Output.DICT,
                timeout=remaining_timeout,
            )
            lines: dict[tuple, dict] = {}
            for i, word in enumerate(data["text"]):
                word = (word or "").strip()
                conf = float(data["conf"][i])
                if not word or conf < 0:
                    continue
                key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
                left, top = data["left"][i], data["top"][i]
                right, bottom = left + data["width"][i], top + data["height"][i]
                line = lines.setdefault(
                    key, {"words": [], "confs": [], "box": [left, top, right, bottom]}
                )
                line["words"].append(word)
                line["confs"].append(conf / 100.0)
                box = line["box"]
                line["box"] = [
                    min(box[0], left),
                    min(box[1], top),
                    max(box[2], right),
                    max(box[3], bottom),
                ]
            blocks = []
            for line in lines.values():
                conf = sum(line["confs"]) / len(line["confs"])
                confidences.extend(line["confs"])
                left, top, right, bottom = line["box"]
                blocks.append(
                    {
                        "block_id": f"p{page_number}_block_{len(blocks) + 1:04d}",
                        "text": " ".join(line["words"]),
                        "confidence": round(conf, 4),
                        "bounding_box": {
                            "left": left,
                            "top": top,
                            "width": right - left,
                            "height": bottom - top,
                        },
                    }
                )
            pages.append({"page_number": page_number, "text_blocks": blocks})
            texts.append("\n".join(block["text"] for block in blocks))

        average = sum(confidences) / len(confidences) if confidences else 0.0
        return OcrResult(
            engine_name=self.name,
            full_text="\n\n".join(texts).strip(),
            pages=pages,
            average_confidence=round(average, 4),
            duration_ms=int((time.perf_counter() - start) * 1000),
            note=f"Tesseract languages: {self.languages}.",
        )
