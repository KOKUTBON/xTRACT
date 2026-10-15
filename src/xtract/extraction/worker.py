from __future__ import annotations

import hashlib
import json
import logging

from xtract.extraction.extractor import MetadataExtractor
from xtract.storage.database import RuntimeDatabase
from xtract.storage.queue import Job, JobQueue
from xtract.storage.storage import ObjectStorageClient

logger = logging.getLogger("extraction-worker")


def schedule_integration(queue: JobQueue, document: dict, requested_by: str) -> None:
    """Queue protocol delivery for a document that has just been validated."""
    queue.enqueue(
        job_type="integration.dispatch_protocol",
        owning_service_id="integration-hub",
        institution_id=document["institution_id"],
        payload={"document_id": document["document_id"], "requested_by": requested_by},
        document_id=document["document_id"],
        idempotency_scope="document",
        idempotency_key=f"integration:{document['document_id']}",
        priority="normal",
    )


class ExtractionWorker:
    """Executes extraction.extract_metadata jobs and gates results through human review."""

    def __init__(
        self,
        queue: JobQueue,
        database: RuntimeDatabase,
        storage: ObjectStorageClient,
        extractor: MetadataExtractor,
    ) -> None:
        self.queue = queue
        self.db = database
        self.storage = storage
        self.extractor = extractor

    def process_job(self, job: Job) -> dict:
        document_id = job.payload.get("document_id") or job.document_id
        doc = self.db.get_document(document_id)
        if not doc:
            raise ValueError(f"Document {document_id} does not exist")
        institution_id = doc["institution_id"]
        text = self.db.get_document_text(document_id)
        requested_family = doc["metadata_json"].get("requested_family", doc["document_family"])

        extraction_run = self.extractor.extract(
            document_id=document_id,
            document_family=requested_family,
            ocr_output={"full_text": text["full_text"], "pages": text["pages"]},
            source_ocr_path=f"ocr-artifacts/{institution_id}/{document_id}/ocr_text.txt",
        )
        run_id = extraction_run["run_id"]
        family = extraction_run["document_family"]
        candidate = extraction_run["document_type_candidate"]

        run_bytes = json.dumps(extraction_run, indent=2).encode("utf-8")
        run_key = f"{institution_id}/{document_id}/{run_id}.extraction.json"
        self.storage.put_object("documents-derivatives", run_key, run_bytes, "application/json")
        self.db.record_blob_object(
            document_id=document_id,
            bucket_name="documents-derivatives",
            object_key=run_key,
            blob_class="derivative_document",
            content_type="application/json",
            sha256=hashlib.sha256(run_bytes).hexdigest(),
            byte_size=len(run_bytes),
        )

        self.db.cancel_review_tasks(document_id, "extraction-engine", "Superseded by a new run")
        self.db.replace_field_values(
            document_id, run_id, extraction_run["field_results"], "service:extraction-engine"
        )

        tasks = []
        for field in extraction_run["field_results"]:
            if not field["review_required"]:
                continue
            tasks.append(
                self.db.create_review_task(
                    document_id=document_id,
                    queue_name=f"{family}_review",
                    priority="high" if field.get("required") else "normal",
                    reason_codes=field["review_reason_codes"],
                    payload={
                        "field_code": field["field_code"],
                        "label": field["label"],
                        "current_value": field["normalized_value"],
                        "confidence_score": field["confidence_score"],
                        "run_id": run_id,
                    },
                )
            )

        needs_review = bool(tasks)
        stage = "to_be_verified" if needs_review else "validated"
        self.db.update_document_stage(
            document_id=document_id,
            workflow_stage=stage,
            document_family=family,
            metadata_update={
                "extraction_run_id": run_id,
                "document_type_code": candidate["type_code"],
                "document_type_display_name": candidate["display_name"],
                "document_type_confidence": candidate["confidence_score"],
                "review_tasks_count": len(tasks),
            },
        )
        self.db.record_audit_event(
            event_type="extraction.completed",
            institution_id=institution_id,
            document_id=document_id,
            actor_type="service",
            actor_id="extraction-engine",
            action_code="EXTRACTION_COMPLETED",
            payload={
                "run_id": run_id,
                "document_family": family,
                "document_type": candidate["type_code"],
                "fields": len(extraction_run["field_results"]),
                "fields_needing_review": len(tasks),
            },
        )
        if needs_review:
            self.db.record_audit_event(
                event_type="review.requested",
                institution_id=institution_id,
                document_id=document_id,
                actor_type="service",
                actor_id="extraction-engine",
                action_code="REVIEW_REQUESTED",
                payload={
                    "pending_tasks": len(tasks),
                    "fields": [task["payload_json"]["field_code"] for task in tasks],
                },
            )
        else:
            self.db.record_audit_event(
                event_type="review.completed",
                institution_id=institution_id,
                document_id=document_id,
                actor_type="service",
                actor_id="extraction-engine",
                action_code="AUTO_VALIDATED",
                payload={"reason": "All fields met confidence and validation thresholds"},
            )
            schedule_integration(self.queue, doc, "extraction-engine")

        return {
            "run_id": run_id,
            "document_id": document_id,
            "document_family": family,
            "needs_human_review": needs_review,
            "review_tasks_created": len(tasks),
            "storage_path": f"documents-derivatives/{run_key}",
        }
