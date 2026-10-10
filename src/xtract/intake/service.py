from __future__ import annotations

import hashlib
import mimetypes
import re
import uuid
from pathlib import Path

from xtract.intake.config import IntakeConfig
from xtract.storage.database import RuntimeDatabase
from xtract.storage.queue import Job, JobQueue
from xtract.storage.storage import ObjectStorageClient

AUTO_FAMILY = "auto"

# Leading bytes used to confirm the declared media type of binary uploads.
MAGIC_SIGNATURES = {
    "application/pdf": [b"%PDF-"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/tiff": [b"II*\x00", b"MM\x00*"],
    "image/bmp": [b"BM"],
    "image/webp": [b"RIFF"],
}


class IntakeError(Exception):
    """Domain error raised during intake operations."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def sanitize_filename(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name.strip()
    name = re.sub(r"[^\w.\- ]+", "_", name).strip(" .")
    return name[:180] or "document"


def guess_mime_type(filename: str, content: bytes) -> str:
    for mime_type, signatures in MAGIC_SIGNATURES.items():
        if any(content.startswith(signature) for signature in signatures):
            if mime_type == "image/webp" and content[8:12] != b"WEBP":
                continue
            return mime_type
    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        return guessed
    try:
        content[:4096].decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return "application/octet-stream"


class IntakeService:
    """Validates, stores, registers, and schedules incoming documents for OCR."""

    def __init__(
        self,
        config: IntakeConfig,
        database: RuntimeDatabase,
        storage: ObjectStorageClient,
        queue: JobQueue,
    ) -> None:
        self.config = config
        self.db = database
        self.storage = storage
        self.queue = queue

    def _validate(self, filename: str, content: bytes, mime_type: str | None) -> str:
        byte_size = len(content)
        if byte_size == 0:
            raise IntakeError("EMPTY_PAYLOAD", "Cannot ingest an empty document.")
        if byte_size > self.config.max_file_size_bytes:
            raise IntakeError(
                "PAYLOAD_TOO_LARGE",
                f"File size {byte_size} exceeds the limit of "
                f"{self.config.max_file_size_bytes} bytes.",
            )

        declared = (mime_type or "").split(";")[0].strip().lower()
        if not declared or declared == "application/octet-stream":
            declared = guess_mime_type(filename, content)
        if declared not in self.config.allowed_mime_types:
            raise IntakeError(
                "UNSUPPORTED_MEDIA_TYPE",
                f"Media type '{declared}' is not supported. "
                f"Allowed: {', '.join(sorted(self.config.allowed_mime_types))}.",
            )
        signatures = MAGIC_SIGNATURES.get(declared)
        if signatures and not any(content.startswith(sig) for sig in signatures):
            raise IntakeError(
                "MEDIA_TYPE_MISMATCH",
                f"The file content does not look like '{declared}'.",
            )
        return declared

    def ingest_document(
        self,
        institution_id: str,
        office_id: str,
        document_family: str,
        filename: str,
        content: bytes,
        mime_type: str | None = None,
        title: str | None = None,
        source_channel: str = "manual_upload",
        metadata: dict | None = None,
        routing_hint: str | None = None,
        actor_id: str = "intake-service",
    ) -> tuple[dict, Job]:
        """Ingest, validate, store, and enqueue a document for OCR."""
        filename = sanitize_filename(filename)
        mime_type = self._validate(filename, content, mime_type)
        sha256_hash = hashlib.sha256(content).hexdigest()

        if self.config.reject_duplicates:
            duplicate = self.db.find_document_by_sha256(institution_id, sha256_hash)
            if duplicate:
                raise IntakeError(
                    "DUPLICATE_DOCUMENT",
                    f"An identical file was already ingested as '{duplicate.get('title')}'.",
                    {"document_id": duplicate["document_id"]},
                )

        document_id = str(uuid.uuid4())
        source_ingest_id = f"ingest-{document_id[:8]}"
        object_key = f"{institution_id}/{document_id}/{filename}"
        storage_uri = self.storage.put_object(
            storage_class="documents-source",
            key=object_key,
            data=content,
            content_type=mime_type,
        )

        initial_meta = {
            "source_channel": source_channel,
            "original_filename": filename,
            "source_object_key": object_key,
            "mime_type": mime_type,
            "byte_size": len(content),
            "sha256": sha256_hash,
            "routing_hint": routing_hint,
            "requested_family": document_family or AUTO_FAMILY,
        }
        if metadata:
            initial_meta.update(metadata)

        doc = self.db.create_document(
            institution_id=institution_id,
            office_id=office_id,
            document_family=document_family or AUTO_FAMILY,
            source_ingest_id=source_ingest_id,
            title=(title or "").strip() or filename,
            document_id=document_id,
            initial_metadata=initial_meta,
            initial_stage="acquired",
        )
        self.db.record_blob_object(
            document_id=document_id,
            bucket_name="documents-source",
            object_key=object_key,
            blob_class="source",
            content_type=mime_type,
            sha256=sha256_hash,
            byte_size=len(content),
        )
        self.db.record_audit_event(
            event_type="document.acquired",
            institution_id=institution_id,
            document_id=document_id,
            actor_type="operator" if actor_id != "intake-service" else "service",
            actor_id=actor_id,
            action_code="DOCUMENT_ACQUIRED",
            payload={
                "source_ingest_id": source_ingest_id,
                "filename": filename,
                "mime_type": mime_type,
                "sha256": sha256_hash,
                "byte_size": len(content),
                "storage_uri": storage_uri,
            },
        )

        job = self.queue.enqueue(
            job_type="ocr.process_document",
            owning_service_id="ocr-orchestrator",
            institution_id=institution_id,
            payload={
                "document_id": document_id,
                "institution_id": institution_id,
                "office_id": office_id,
                "document_family": document_family or AUTO_FAMILY,
                "object_key": object_key,
                "filename": filename,
                "mime_type": mime_type,
                "sha256": sha256_hash,
                "routing_hint": routing_hint,
            },
            document_id=document_id,
            idempotency_scope="document",
            idempotency_key=f"ocr:{document_id}",
            priority="high",
        )
        return doc, job
