from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from xtract.storage.database import RuntimeDatabase
from xtract.storage.queue import JobQueue

PROCESSING_STAGES = {"acquired", "ocr_executed"}
REVIEW_STAGE = "to_be_verified"
VALIDATED_STAGES = {"validated", "protocol_pending", "protocol_registered"}
TERMINAL_STAGES = {"discarded"}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_rfc3339(value: str | None) -> str:
    """SQLite stores ISO timestamps with +00:00; normalize them for JSON Schema date-time."""
    if not value:
        return now_utc()
    return value.replace("+00:00", "Z")


def first_line(value: str | None, max_length: int = 120) -> str:
    text = " ".join((value or "").split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def _load(source: dict | Path | None) -> dict:
    if isinstance(source, Path) and source.is_file():
        return json.loads(source.read_text(encoding="utf-8"))
    if isinstance(source, dict):
        return source
    return {"exceptions": []}


class BackofficeProjections:
    """Read models for the review queue, document workspace, exception inbox, and search."""

    def __init__(
        self,
        database: RuntimeDatabase,
        queue: JobQueue | None = None,
        exception_taxonomy: dict | Path | None = None,
        field_taxonomy: dict | None = None,
    ) -> None:
        self.db = database
        self.queue = queue
        self.taxonomy = _load(exception_taxonomy)
        self.exceptions_map = {
            item["exception_code"]: item for item in self.taxonomy.get("exceptions", [])
        }
        self.field_patterns: dict[tuple[str, str], str | None] = {}
        for doc_type in (field_taxonomy or {}).get("document_types", []):
            for field in doc_type.get("fields", []):
                key = (doc_type["family_code"], field["field_code"])
                self.field_patterns[key] = field.get("validation_pattern")

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _display_name(doc: dict) -> str:
        meta = doc.get("metadata_json", {})
        if meta.get("document_type_display_name"):
            return meta["document_type_display_name"]
        if doc["current_workflow_stage"] in PROCESSING_STAGES:
            return "Processing…"
        if doc.get("document_family") in (None, "", "auto"):
            return "Unclassified"
        return doc.get("document_family", "document").replace("_", " ").capitalize()

    @staticmethod
    def _filename(doc: dict) -> str:
        meta = doc.get("metadata_json", {})
        return doc.get("title") or meta.get("original_filename") or f"{doc['document_id']}"

    def _excerpt(self, doc: dict) -> str:
        return first_line(self.db.get_document_text(doc["document_id"])["full_text"]) or (
            "Waiting for OCR" if doc["current_workflow_stage"] in PROCESSING_STAGES else ""
        )

    # ------------------------------------------------------------------ review queue

    def get_review_queue(self, institution_id: str | None = None) -> dict:
        """One queue item per document awaiting human verification."""
        pending: dict[str, list[dict]] = {}
        for task in self.db.get_review_tasks(task_status="PENDING"):
            pending.setdefault(task["document_id"], []).append(task)

        items = []
        for doc in self.db.query_documents(
            workflow_stage=REVIEW_STAGE, institution_id=institution_id, limit=10_000
        ):
            if institution_id and doc["institution_id"] != institution_id:
                continue
            tasks = pending.get(doc["document_id"], [])
            reason_codes = sorted({code for task in tasks for code in task["reason_codes"]})
            priority = "high" if any(task["priority"] == "high" for task in tasks) else "normal"
            excerpt = (
                f"{len(tasks)} field(s) to verify · "
                + ", ".join(task["payload_json"].get("label") or "" for task in tasks)
                if tasks
                else "All fields checked · ready to complete"
            )
            items.append(
                {
                    "task_id": tasks[0]["review_task_id"] if tasks else doc["document_id"],
                    "document_id": doc["document_id"],
                    "institution_id": doc["institution_id"],
                    "office_id": doc["office_id"],
                    "workflow_stage": doc["current_workflow_stage"],
                    "queue_status": "ready" if tasks else "in_review",
                    "priority": priority,
                    "reason_codes": reason_codes or ["operator_review_required"],
                    "document_summary": {
                        "source_filename": self._filename(doc),
                        "document_type_display_name": self._display_name(doc),
                        "excerpt": excerpt,
                    },
                    "assigned_role": tasks[0].get("assigned_role") if tasks else "operator",
                    "available_actions": [
                        "open_workspace",
                        "correct_field",
                        "complete_review",
                        "request_reprocessing",
                        "discard_document",
                    ],
                }
            )
        items.sort(key=lambda item: (item["priority"] != "high", item["queue_status"] != "ready"))
        ready = sum(1 for item in items if item["queue_status"] == "ready")
        return {
            "schema_version": "1.0.0",
            "generated_at": now_utc(),
            "items": items,
            "summary": {"total_items": len(items), "ready_items": ready, "blocked_items": 0},
        }

    # ------------------------------------------------------------------ workspace

    def _field_panels(self, doc: dict) -> list[dict]:
        document_id = doc["document_id"]
        revisions: dict[str, list[dict]] = {}
        for revision in self.db.get_field_revisions(document_id):
            revisions.setdefault(revision["field_code"], []).append(revision)

        panels = []
        for field in self.db.get_field_values(document_id):
            history = revisions.get(field["field_code"], [])
            validated = [r for r in history if r["lifecycle_stage"] == "validated"]
            panels.append(
                {
                    "field_code": field["field_code"],
                    "label": field["label"],
                    "value_type": field["value_type"],
                    "required": field["required"],
                    "validation_pattern": self.field_patterns.get(
                        (doc["document_family"], field["field_code"])
                    ),
                    "extracted_value": field["extracted_value"],
                    "validated_value": validated[-1]["value"] if validated else None,
                    "current_value": field["current_value"],
                    "review_required": field["review_required"],
                    "review_reason_codes": field["review_reason_codes"],
                    "confidence_score": field["confidence_score"],
                    "source_text": field["source_text"],
                    "source_page_number": field["source_page_number"],
                    "aliases": [],
                    "snapshots": [
                        {
                            "lifecycle_stage": revision["lifecycle_stage"],
                            "value": revision["value"],
                            "created_at": to_rfc3339(revision["created_at"]),
                            "created_by": revision["actor_id"],
                            "note": revision["note"] or "",
                        }
                        for revision in history
                    ],
                }
            )
        return panels

    def permitted_actions(
        self, doc: dict, pending_tasks: list[dict], exceptions: list[dict]
    ) -> list[str]:
        stage = doc["current_workflow_stage"]
        if stage in TERMINAL_STAGES or self.queue.has_active_jobs(doc["document_id"]):
            return ["open_audit"]
        actions = ["open_audit", "request_reprocessing"]
        if stage == REVIEW_STAGE:
            actions = ["correct_field", "complete_review", "discard_document", *actions]
        elif stage in VALIDATED_STAGES:
            actions = ["correct_field", "reopen_review", *actions]
        else:
            actions.append("discard_document")
        open_protocol = any(
            e["exception_code"] == "protocol_system_unavailable" and e["exception_status"] == "open"
            for e in exceptions
        )
        if stage in {"validated", "protocol_pending"} or open_protocol:
            actions.append("retry_integration")
        return actions

    def get_document_workspace(self, document_id: str) -> dict | None:
        doc = self.db.get_document(document_id)
        if not doc:
            return None
        meta = doc["metadata_json"]
        stage = doc["current_workflow_stage"]
        tasks = self.db.get_review_tasks(document_id=document_id)
        pending = [task for task in tasks if task["task_status"] == "PENDING"]
        exceptions = self.db.get_exceptions(document_id=document_id)
        text = self.db.get_document_text(document_id)

        if pending:
            queue_context = {
                "task_id": pending[0]["review_task_id"],
                "queue_status": "ready",
                "priority": "high" if any(t["priority"] == "high" for t in pending) else "normal",
                "reason_codes": sorted({code for t in pending for code in t["reason_codes"]}),
            }
        else:
            queue_context = {
                "task_id": None,
                "queue_status": "completed" if stage not in PROCESSING_STAGES else "blocked",
                "priority": "low",
                "reason_codes": [],
            }

        review_history = [
            {
                "decision": (task["payload_json"].get("resolution_action") or "confirm").lower(),
                "target_id": task["payload_json"].get("field_code", task["review_task_id"]),
                "reason": ",".join(task["reason_codes"]) or "operator_confirmation",
                "comment": task["payload_json"].get("comment", ""),
                "reviewed_by": task["payload_json"].get("resolved_by", "operator"),
                "reviewed_at": to_rfc3339(
                    task["payload_json"].get("resolved_at") or task["updated_at"]
                ),
            }
            for task in tasks
            if task["task_status"] == "RESOLVED"
        ]

        audit_timeline = []
        for event in self.db.get_audit_events(document_id):
            payload = event.get("payload_json", {})
            summary = ", ".join(
                f"{key}={value}"
                for key, value in sorted(payload.items())
                if not isinstance(value, (dict, list))
            )
            audit_timeline.append(
                {
                    "event_type": event["event_type"],
                    "occurred_at": to_rfc3339(event["event_timestamp"]),
                    "actor_id": event["actor_id"],
                    "outcome": "failure" if event["event_type"].endswith("failed") else "success",
                    "details_summary": summary,
                }
            )

        exception_context = [
            {
                "exception_id": exc["exception_id"],
                "exception_code": exc["exception_code"],
                "status": exc["exception_status"],
                "severity": exc["severity"],
                "opened_at": to_rfc3339(exc["first_seen_at"]),
                "message": exc["payload_json"].get("message")
                or self.exceptions_map.get(exc["exception_code"], {}).get("description", ""),
            }
            for exc in exceptions
        ]

        external_references = []
        for ref in self.db.get_external_references(document_id):
            item = {
                "system_name": ref["target_system"],
                "reference_type": ref["reference_type"],
                "reference_id": ref["authoritative_value"],
                "status": ref["sync_status"],
                "synchronized_at": to_rfc3339(ref.get("synced_at")),
            }
            if ref["metadata_json"].get("uri"):
                item["uri"] = ref["metadata_json"]["uri"]
            external_references.append(item)

        jobs = self.queue.list_jobs(document_id=document_id, limit=20) if self.queue else []
        processing_active = stage in PROCESSING_STAGES or any(
            job.status in ("pending", "processing") for job in jobs
        )

        return {
            "schema_version": "1.0.0",
            "document_id": document_id,
            "institution_id": doc["institution_id"],
            "office_id": doc["office_id"],
            "document_summary": {
                "title": self._filename(doc),
                "document_family": doc["document_family"],
                "document_type_code": meta.get("document_type_code"),
                "document_type_display_name": meta.get("document_type_display_name"),
                "mime_type": meta.get("mime_type"),
                "byte_size": meta.get("byte_size"),
                "sha256": meta.get("sha256"),
                "created_at": to_rfc3339(doc["created_at"]),
                "ocr_engine": meta.get("ocr_selected_engine"),
                "ocr_confidence": meta.get("ocr_avg_confidence"),
                "registration_reference": meta.get("registration_reference"),
            },
            "workflow_state": {
                "stage": stage,
                "updated_at": to_rfc3339(doc["updated_at"]),
                "updated_by": meta.get("stage_updated_by", "system"),
                "reason": meta.get("stage_reason", ""),
            },
            "queue_context": queue_context,
            "viewer": {
                "source_filename": self._filename(doc),
                "page_count": int(meta.get("page_count", 1) or 1),
                "ocr_text": text["full_text"],
                "review_copy_path": f"ocr-artifacts/{doc['institution_id']}/{document_id}/"
                "normalized_review_copy.txt",
            },
            "field_panels": self._field_panels(doc),
            "review_history": review_history,
            "audit_timeline": audit_timeline,
            "exception_context": exception_context,
            "external_references": external_references,
            "permitted_actions": self.permitted_actions(doc, pending, exceptions),
            "processing": {
                "active": processing_active,
                "jobs": [
                    {
                        "job_id": job.job_id,
                        "job_type": job.job_type,
                        "status": job.status,
                        "attempts": job.attempts,
                        "max_attempts": job.max_attempts,
                        "last_error_message": job.last_error_message,
                        "created_at": to_rfc3339(job.created_at),
                        "updated_at": to_rfc3339(job.updated_at),
                    }
                    for job in jobs
                ],
            },
        }

    # ------------------------------------------------------------------ exceptions

    def get_exception_inbox(
        self, institution_id: str | None = None, status: str | None = None
    ) -> dict:
        items = []
        for exc in self.db.get_exceptions(status=status, institution_id=institution_id):
            doc = self.db.get_document(exc["document_id"])
            if not doc or (institution_id and doc["institution_id"] != institution_id):
                continue
            code = exc["exception_code"]
            definition = self.exceptions_map.get(code, {})
            resolved = exc["exception_status"] == "resolved"
            item = {
                "exception_id": exc["exception_id"],
                "document_id": exc["document_id"],
                "institution_id": doc["institution_id"],
                "stage_id": definition.get("stage_id", doc["current_workflow_stage"]),
                "exception_code": code,
                "category": definition.get("category", "system"),
                "severity": exc.get("severity") or definition.get("severity", "medium"),
                "status": exc["exception_status"],
                "source_system": exc.get("source_service", "system"),
                "message": exc["payload_json"].get("message")
                or definition.get("description", f"Exception {code}"),
                "recommended_action": definition.get(
                    "recommended_action", "Review the document and request reprocessing."
                ),
                "allowed_actions": [] if resolved else ["reprocess_document", "mark_resolved"],
                "opened_at": to_rfc3339(exc["first_seen_at"]),
                "audit_event_ids": [],
            }
            if exc.get("resolved_at"):
                item["resolved_at"] = to_rfc3339(exc["resolved_at"])
            items.append(item)
        open_items = sum(1 for item in items if item["status"] == "open")
        return {
            "schema_version": "1.0.0",
            "generated_at": now_utc(),
            "items": items,
            "summary": {
                "total_items": len(items),
                "open_items": open_items,
                "resolved_items": len(items) - open_items,
            },
        }

    # ------------------------------------------------------------------ search

    def search_documents(
        self,
        text_query: str | None = None,
        workflow_stage: str | None = None,
        institution_id: str | None = None,
        limit: int = 200,
    ) -> dict:
        hits = []
        for doc in self.db.query_documents(
            text_query=text_query,
            workflow_stage=workflow_stage,
            institution_id=institution_id,
            limit=limit,
        ):
            document_id = doc["document_id"]
            fields = self.db.get_field_values(document_id)
            excerpt = self._excerpt(doc)
            if text_query:
                full_text = self.db.get_document_text(document_id)["full_text"]
                position = full_text.lower().find(text_query.lower())
                if position >= 0:
                    excerpt = first_line(full_text[max(0, position - 60) : position + 120], 180)
            hits.append(
                {
                    "document_id": document_id,
                    "institution_id": doc["institution_id"],
                    "office_id": doc["office_id"],
                    "workflow_stage": doc["current_workflow_stage"],
                    "source_filename": self._filename(doc),
                    "document_type_display_name": self._display_name(doc),
                    "matched_metadata": [
                        {
                            "field_code": f["field_code"],
                            "label": f["label"],
                            "value": f["current_value"],
                        }
                        for f in fields
                        if f["current_value"] not in (None, "")
                        and (
                            not text_query or text_query.lower() in str(f["current_value"]).lower()
                        )
                    ],
                    "matched_text_excerpt": excerpt,
                    "external_reference_ids": [
                        ref["authoritative_value"]
                        for ref in self.db.get_external_references(document_id)
                    ],
                }
            )
        return {
            "schema_version": "1.0.0",
            "generated_at": now_utc(),
            "applied_filters": {
                "text_query": text_query,
                "workflow_stage": workflow_stage,
                "institution_id": institution_id,
            },
            "hits": hits,
        }

    def get_stats(self, institution_id: str | None = None) -> dict:
        stages = self.db.count_documents_by_stage(institution_id)
        return {
            "generated_at": now_utc(),
            "documents_total": sum(stages.values()),
            "documents_by_stage": stages,
            "pending_review": stages.get(REVIEW_STAGE, 0),
            "processing": sum(stages.get(stage, 0) for stage in PROCESSING_STAGES),
            "validated": sum(stages.get(stage, 0) for stage in VALIDATED_STAGES),
            "open_exceptions": len(
                self.db.get_exceptions(status="open", institution_id=institution_id)
            ),
            "jobs_by_status": self.queue.count_by_status(institution_id) if self.queue else {},
        }
