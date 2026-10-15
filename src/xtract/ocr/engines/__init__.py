from __future__ import annotations

from xtract.ocr.engines.base import OcrEngine, OcrEngineUnavailable, OcrResult
from xtract.ocr.engines.pdf_text_engine import PdfTextLayerEngine
from xtract.ocr.engines.tesseract_engine import TesseractOcrEngine
from xtract.ocr.engines.text_engine import PlainTextEngine


def default_engines(languages: str | None = None) -> dict[str, OcrEngine]:
    engines: list[OcrEngine] = [
        PlainTextEngine(),
        PdfTextLayerEngine(),
        TesseractOcrEngine(languages=languages),
    ]
    return {engine.name: engine for engine in engines}


__all__ = [
    "OcrEngine",
    "OcrEngineUnavailable",
    "OcrResult",
    "PdfTextLayerEngine",
    "PlainTextEngine",
    "TesseractOcrEngine",
    "default_engines",
]
