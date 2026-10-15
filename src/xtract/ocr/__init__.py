"""xTRACT OCR orchestrator and pluggable engine implementations."""

from xtract.ocr.engines import (
    OcrEngine,
    OcrEngineUnavailable,
    OcrResult,
    PdfTextLayerEngine,
    PlainTextEngine,
    TesseractOcrEngine,
    default_engines,
)
from xtract.ocr.orchestrator import OcrOrchestrator, OcrProcessingError

__all__ = [
    "OcrEngine",
    "OcrEngineUnavailable",
    "OcrOrchestrator",
    "OcrProcessingError",
    "OcrResult",
    "PdfTextLayerEngine",
    "PlainTextEngine",
    "TesseractOcrEngine",
    "default_engines",
]
