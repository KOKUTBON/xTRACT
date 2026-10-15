"""xTRACT intake service: document validation, deduplication, and initial ingestion."""

from xtract.intake.config import IntakeConfig
from xtract.intake.service import IntakeError, IntakeService

__all__ = ["IntakeConfig", "IntakeError", "IntakeService"]
