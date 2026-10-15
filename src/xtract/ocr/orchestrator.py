from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from xtract.ocr.engines import OcrEngine, OcrEngineUnavailable, OcrResult, default_engines
from xtract.storage.database import RuntimeDatabase
from xtract.storage.queue import Job, JobQueue
from xtract.storage.storage import ObjectStorageClient

logger = logging.getLogger("ocr-orchestrator")

DEFAULT_POLICY = {
    "version": "1.0.0",
    "engines": [],
    "preprocess_profiles": [{"profile_id": "standard", "steps": ["grayscale"]}],
    "default_route": {
        "preprocess_profile_id": "standard",
        "preferred_engines": ["text", "pdf_text", "tesseract"],
        "min_confidence": 0.6,
        "min_text_accuracy": 0.9,
    },
    "routes": [],
}


class OcrProcessingError(RuntimeError):
    """Raised when no OCR engine could produce a result for a document."""

    def __init__(self, message: str, attempts: list[dict]) -> None:
        super().__init__(message)
        self.attempts = attempts


class OcrOrchestrator:
    """Routes documents through OCR engines with confidence-based fallback."""

    def __init__(
        self,
        database: RuntimeDatabase,
        storage: ObjectStorageClient,
        queue: JobQueue,
        routing_policy: dict | Path | None = None,
        engines: dict[str, OcrEngine] | None = None,
    ) -> None:
        self.db = database
        self.storage = storage
        self.queue = queue
        if isinstance(routing_policy, Path):
            self.policy = json.loads(routing_policy.read_text(encoding="utf-8"))
        else:
            self.policy = routing_policy or DEFAULT_POLICY
        disabled = {
            engine["engine_id"]
            for engine in self.policy.get("engines", [])
            if not engine.get("enabled", True)
        }
        self.engines = {
            name: engine
            for name, engine in (engines if engines is not None else default_engines()).items()
            if name not in disabled
        }

    def engine_status(self) -> list[dict]:
        status = []
        for name, engine in self.engines.items():
            available, reason = engine.availability()
            status.append(
                {
                    "engine_id": name,
                    "available": available,
                    "reason": reason,
                    "media_types": list(engine.media_types),
                }
            )
        return status

    def _route(self, document_family: str) -> dict:
        for route in self.policy.get("routes", []):
            if route.get("document_family") == document_family:
                return route
        return self.policy.get("default_route", DEFAULT_POLICY["default_route"])

    def _profile_steps(self, profile_id: str) -> list[str]:
        for profile in self.policy.get("preprocess_profiles", []):
            if profile.get("profile_id") == profile_id:
                return list(profile.get("steps", []))
        return []

    def run_engines(
        self, content: bytes, filename: str, mime_type: str, document_family: str
    ) -> tuple[OcrResult, list[dict], str, list[str]]:
        route = self._route(document_family)
        profile_id = route.get("preprocess_profile_id", "standard")
        steps = self._profile_steps(profile_id)
        threshold = float(route.get("min_confidence", 0.6))
        candidates = [
            name
            for name in route.get("preferred_engines", list(self.engines))
            if name in self.engines and self.engines[name].supports(mime_type)
        ]

        attempts: list[dict] = []
        best: OcrResult | None = None
        for name in candidates:
            engine = self.engines[name]
            available, reason = engine.availability()
            if not available:
                attempts.append({"engine_id": name, "status": "unavailable", "reason": reason})
                continue
            try:
                result = engine.process(content, filename, mime_type, steps)
            except OcrEngineUnavailable as exc:
                attempts.append({"engine_id": name, "status": "unavailable", "reason": str(exc)})
                continue
            except Exception as exc:  # engine crashes must not stop the fallback chain
                logger.exception("OCR engine %s failed", name)
                attempts.append(
                    {"engine_id": name, "status": "engine_failure", "reason": str(exc)[:500]}
                )
                continue

            if result.average_confidence >= threshold and result.full_text.strip():
                attempts.append(
                    {
                        "engine_id": name,
                        "status": "selected",
                        "reason": f"Confidence {result.average_confidence:.2f} met threshold "
                        f"{threshold:.2f}. {result.note}".strip(),
                    }
                )
                return result, attempts, profile_id, steps
            attempts.append(
                {
                    "engine_id": name,
                    "status": "threshold_not_met",
                    "reason": f"Confidence {result.average_confidence:.2f} below threshold "
                    f"{threshold:.2f}. {result.note}".strip(),
                }
            )
            if best is None or result.average_confidence > best.average_confidence:
                best = result

        if best is not None:
            for attempt in attempts:
                if attempt["engine_id"] == best.engine_name:
                    attempt["status"] = "selected"
                    attempt["reason"] += " Kept as the best available result."
            return best, attempts, profile_id, steps

        if not candidates:
            raise OcrProcessingError(f"No OCR engine supports media type '{mime_type}'.", attempts)
        raise OcrProcessingError("No OCR engine could process the document.", attempts)

    def process_job(self, job: Job) -> dict:
        payload = job.payload
        document_id = payload["document_id"]
        doc = self.db.get_document(document_id)
        if not doc:
            raise ValueError(f"Document {document_id} does not exist")
        institution_id = doc["institution_id"]
        meta = doc["metadata_json"]
        filename = meta.get("original_filename") or payload.get("filename", "document")
        mime_type = meta.get("mime_type") or payload.get("mime_type", "application/octet-stream")
        object_key = meta.get("source_object_key") or f"{institution_id}/{document_id}/{filename}"
        content = self.storage.get_object("documents-source", object_key)

        try:
            result, attempts, profile_id, steps = self.run_engines(
                content, filename, mime_type, doc["document_family"]
            )
        except OcrProcessingError as exc:
            self.db.update_document_stage(
                document_id, "failed", {"failure_reason": str(exc), "ocr_attempts": exc.attempts}
            )
            self.db.record_exception(
                document_id=document_id,
                exception_code="ocr_engine_failure",
                severity="high",
                source_service="ocr-orchestrator",
                payload={"message": str(exc), "attempted_engines": exc.attempts},
            )
            self.db.record_audit_event(
                event_type="document.failed",
                institution_id=institution_id,
                document_id=document_id,
                actor_type="service",
                actor_id="ocr-orchestrator",
                action_code="OCR_FAILED",
                payload={"reason": str(exc)},
            )
            return {"document_id": document_id, "processing_status": "failed", "error": str(exc)}

        full_text = result.full_text
        pages = result.pages
        prefix = f"{institution_id}/{document_id}"
        artifacts = {
            "normalized_review_copy": (
                f"{prefix}/normalized_review_copy.txt",
                (full_text + "\n").encode("utf-8"),
                "text/plain",
            ),
            "ocr_text": (
                f"{prefix}/ocr_text.txt",
                (full_text + "\n").encode("utf-8"),
                "text/plain",
            ),
            "bounding_boxes": (
                f"{prefix}/bounding_boxes.json",
                json.dumps({"pages": pages}, indent=2).encode("utf-8"),
                "application/json",
            ),
            "engine_attempt_trace": (
                f"{prefix}/engine_attempt_trace.json",
                json.dumps({"attempted_engines": attempts}, indent=2).encode("utf-8"),
                "application/json",
            ),
        }
        derived_artifacts = []
        for artifact_id, (key, data, media_type) in artifacts.items():
            self.storage.put_object("ocr-artifacts", key, data, media_type)
            derived_artifacts.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_id,
                    "path": f"ocr-artifacts/{key}",
                    "media_type": media_type,
                }
            )

        block_count = sum(len(page.get("text_blocks", [])) for page in pages)
        normalized_output = {
            "schema_version": "1.0.0",
            "job_id": job.job_id,
            "batch_id": str(uuid.uuid4()),
            "document_id": document_id,
            "tenant_id": institution_id,
            "institution_id": institution_id,
            "office_id": doc["office_id"],
            "source_media_type": mime_type,
            "source_checksum_sha256": meta.get("sha256") or "0" * 64,
            "dedup_status": "processed",
            "processing_status": "success",
            "preprocess_profile_id": profile_id,
            "preprocess_steps": steps,
            "selected_engine": result.engine_name,
            "attempted_engines": attempts,
            "pages": pages,
            "full_text": full_text,
            "metrics": {
                "avg_confidence": round(result.average_confidence, 4),
                "text_accuracy": round(result.average_confidence, 4),
                "block_count": block_count,
                "character_count": len(full_text),
            },
            "derived_artifacts": derived_artifacts,
        }
        self.storage.put_object(
            "ocr-artifacts",
            f"{prefix}/normalized_output.json",
            json.dumps(normalized_output, indent=2).encode("utf-8"),
            "application/json",
        )

        self.db.save_document_text(document_id, full_text, pages)
        self.db.update_document_stage(
            document_id=document_id,
            workflow_stage="ocr_executed",
            metadata_update={
                "ocr_selected_engine": result.engine_name,
                "ocr_avg_confidence": round(result.average_confidence, 4),
                "ocr_character_count": len(full_text),
                "ocr_duration_ms": result.duration_ms,
                "page_count": max(len(pages), 1),
            },
        )
        self.db.resolve_open_exceptions(
            document_id,
            ["ocr_engine_failure", "ocr_low_text_coverage"],
            {"resolved_by": "ocr-orchestrator", "reason": "OCR completed"},
        )
        if not full_text.strip():
            self.db.record_exception(
                document_id=document_id,
                exception_code="ocr_low_text_coverage",
                severity="high",
                source_service="ocr-orchestrator",
                payload={
                    "message": "OCR produced no text. Check the scan quality or install an OCR "
                    "engine that supports this file type.",
                    "attempted_engines": attempts,
                },
            )
        self.db.record_audit_event(
            event_type="ocr.executed",
            institution_id=institution_id,
            document_id=document_id,
            actor_type="service",
            actor_id="ocr-orchestrator",
            action_code="OCR_EXECUTED",
            payload={
                "selected_engine": result.engine_name,
                "avg_confidence": round(result.average_confidence, 4),
                "character_count": len(full_text),
                "page_count": max(len(pages), 1),
            },
        )

        self.queue.enqueue(
            job_type="extraction.extract_metadata",
            owning_service_id="extraction-engine",
            institution_id=institution_id,
            payload={"document_id": document_id, "ocr_avg_confidence": result.average_confidence},
            document_id=document_id,
            idempotency_scope="document",
            idempotency_key=f"extraction:{document_id}",
            priority="high",
        )
        return {
            "document_id": document_id,
            "processing_status": "success",
            "selected_engine": result.engine_name,
            "avg_confidence": round(result.average_confidence, 4),
            "character_count": len(full_text),
        }
