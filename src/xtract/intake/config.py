from __future__ import annotations

DEFAULT_ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/tiff",
        "image/bmp",
        "image/webp",
        "text/plain",
    }
)


class IntakeConfig:
    """Validation settings applied to every ingested document."""

    def __init__(
        self,
        allowed_mime_types: set[str] | frozenset[str] | None = None,
        max_file_size_bytes: int = 50 * 1024 * 1024,
        reject_duplicates: bool = True,
    ) -> None:
        self.allowed_mime_types = set(allowed_mime_types or DEFAULT_ALLOWED_MIME_TYPES)
        self.max_file_size_bytes = max_file_size_bytes
        self.reject_duplicates = reject_duplicates
