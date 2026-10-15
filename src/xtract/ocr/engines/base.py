"""Base interfaces and data structures for OCR engines."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class OcrResult:
    engine_name: str
    full_text: str
    pages: list[dict] = field(default_factory=list)
    average_confidence: float = 0.0
    duration_ms: int = 0
    note: str = ""


class OcrEngineUnavailable(RuntimeError):
    """Raised when an engine's optional dependencies are not installed."""


class OcrEngine(abc.ABC):
    """Interface for pluggable OCR engines."""

    name: str
    media_types: tuple[str, ...] = ()

    def supports(self, mime_type: str) -> bool:
        return any(
            mime_type == media or (media.endswith("/*") and mime_type.startswith(media[:-1]))
            for media in self.media_types
        )

    def availability(self) -> tuple[bool, str]:
        """Return whether the engine can run here, with a human-readable reason."""
        return True, "available"

    @abc.abstractmethod
    def process(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        preprocess_steps: list[str] | None = None,
    ) -> OcrResult:
        """Run OCR against file bytes and return a normalized result."""
        raise NotImplementedError


def line_blocks(text: str, confidence: float, line_height: int = 16) -> list[dict]:
    """Split text into line blocks with synthetic, monotonic bounding boxes."""
    blocks = []
    for index, line in enumerate((ln.strip() for ln in text.splitlines()), start=1):
        if not line:
            continue
        blocks.append(
            {
                "block_id": f"block_{len(blocks) + 1:04d}",
                "text": line,
                "confidence": round(confidence, 4),
                "bounding_box": {
                    "left": 0,
                    "top": (index - 1) * line_height,
                    "width": len(line) * 8,
                    "height": line_height,
                },
            }
        )
    return blocks
