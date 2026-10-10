"""xTRACT extraction engine: classification, field extraction, and normalization."""

from xtract.extraction.extractor import MetadataExtractor
from xtract.extraction.normalizers import (
    apply_normalization,
    normalize_alphanumeric,
    normalize_fiscal_code,
    normalize_iban,
    normalize_vat_number,
    parse_date,
    parse_decimal,
)
from xtract.extraction.worker import ExtractionWorker, schedule_integration

__all__ = [
    "ExtractionWorker",
    "MetadataExtractor",
    "apply_normalization",
    "normalize_alphanumeric",
    "normalize_fiscal_code",
    "normalize_iban",
    "normalize_vat_number",
    "parse_date",
    "parse_decimal",
    "schedule_integration",
]
