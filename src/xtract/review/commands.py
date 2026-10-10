from __future__ import annotations

import uuid

from xtract.review.projections import REVIEW_STAGE, VALIDATED_STAGES, now_utc
from xtract.storage.database import RuntimeDatabase
from xtract.storage.queue import JobQueue

REPROCESS_SCOPES = {
    "ocr": ("ocr.process_document", "ocr-orchestrator", "acquired"),
    "extraction": ("extraction.extract_metadata", "extraction-engine", "ocr_executed"),
    "integration": ("integration.dispatch_protocol", "integration-hub", None),
}
EDITABLE_STAGES = {REVIEW_STAGE, *VALIDATED_STAGES}


class CommandError(Exception):
    """A rejected operator command, mapped to an HTTP error by the API layer."""

    def __init__(self, code: str, message: str, status: int = 409, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


class BackofficeCommands:
    """State-changing operator actions. Every command writes an audit event."""

    def __init__(self, database: RuntimeDatabase, queue: JobQueue, extractor) -> None:
        self.db = database
        self.queue = queue
        self.extractor = extractor

    # ------------------------------------------------------------------ helpers

    def _document(self, document_id: str) -> dict:
        doc = self.db.get_document(document_id)
        if not doc:
            raise CommandError("NOT_FOUND", f"Document {document_id} not found", 404)
        return doc

    def _ensure_idle(self, document_id: str) -> None:
        if self.queue.has_active_jobs(document_id):
            raise CommandError("BUSY", "The document is still being processed. Try again shortly.")

    def _audit(self, doc: dict, event_type: str, actor: str, action: str, payload: dict) -> None:
        self.db.record_audit_event(
            event_type=event_type,
            institution_id=doc["institution_id"],
            document_id=doc["document_id"],
            actor_type="operator",
            actor_id=actor,
            action_code=action,
            payload=payload,
        )

    def _set_stage(self, doc: dict, stage: str, actor: str, reason: str) -> None:
        self.db.update_document_stage(
            doc["document_id"], stage, {"stage_updated_by": actor, "stage_reason": reason}
        )

    def _schedule_integration(self, doc: dict, actor: str) -> None:
        self.queue.enqueue(
            job_type="integration.dispatch_protocol",
            owning_service_id="integration-hub",
            institution_id=doc["institution_id"],
            payload={"document_id": doc["document_id"], "requested_by": actor},
            document_id=doc["document_id"],
            idempotency_scope="document",
            idempotency_key=f"integration:{doc['document_id']}",
            priority="normal",
        )

    def _resolve_field_tasks(
        self, document_id: str, field_code: str, actor: str, action: str, value, comment: str | None
    ) -> None:
        for task in self.db.get_review_tasks(document_id=document_id, task_status="PENDING"):
            if task["payload_json"].get("field_code") == field_code:
                self.db.resolve_review_task(task["review_task_id"], actor, value, action, comment)

    # ------------------------------------------------------------------ fields

    def update_field(
        self,
        document_id: str,
        field_code: str,
        value: str | None,
        actor: str,
        comment: str | None = None,
        force: bool = False,
    ) -> dict:
        doc = self._document(document_id)
        self._ensure_idle(document_id)
        if doc["current_workflow_stage"] not in EDITABLE_STAGES:
            raise CommandError(
                "INVALID_STAGE",
                f"Fields cannot be edited while the document is '{doc['current_workflow_stage']}'.",
            )
        current = self.db.get_field_value(document_id, field_code)
        if not current:
            raise CommandError("NOT_FOUND", f"Field {field_code} not found", 404)

        definition = self.extractor.field_definition(doc["document_family"], field_code) or {}
        raw = value.strip() if isinstance(value, str) else value
        normalized, problems = self.extractor.validate_value(definition, raw or None)
        if problems and not force:
            raise CommandError(
                "VALIDATION_FAILED",
                f"The value for '{current['label']}' did not pass validation: "
                + ", ".join(problems).replace("_", " ")
                + ". Save again with force to keep it anyway.",
                422,
                {"problems": problems, "normalized_value": normalized},
            )

        confirmed = normalized == current["current_value"]
        action = "CONFIRM" if confirmed else "CORRECT"
        self.db.set_field_value(
            document_id,
            field_code,
            normalized,
            actor,
            "validated",
            comment or ("Confirmed by operator" if confirmed else "Corrected by operator"),
        )
        self._resolve_field_tasks(document_id, field_code, actor, action, normalized, comment)
        self._audit(
            doc,
            "review.field_confirmed" if confirmed else "review.field_corrected",
            actor,
            f"FIELD_{action}ED",
            {
                "field_code": field_code,
                "previous_value": current["current_value"],
                "new_value": normalized,
                "forced": bool(problems),
            },
        )
        return self.db.get_field_value(document_id, field_code) or {}

    def confirm_field(self, document_id: str, field_code: str, actor: str) -> dict:
        current = self.db.get_field_value(document_id, field_code)
        if not current:
            raise CommandError("NOT_FOUND", f"Field {field_code} not found", 404)
        return self.update_field(document_id, field_code, current["current_value"], actor)

    # ------------------------------------------------------------------ review lifecycle

    def complete_review(self, document_id: str, actor: str, comment: str | None = None) -> None:
        doc = self._document(document_id)
        self._ensure_idle(document_id)
        if doc["current_workflow_stage"] != REVIEW_STAGE:
            raise CommandError(
                "INVALID_STAGE", "Only documents awaiting verification can be completed."
            )
        fields = self.db.get_field_values(document_id)
        missing = [f["label"] for f in fields if f["required"] and f["current_value"] in (None, "")]
        if missing:
            raise CommandError(
                "REQUIRED_FIELDS_MISSING",
                "Fill in the required fields before completing the review: " + ", ".join(missing),
                422,
                {"fields": missing},
            )
        for task in self.db.get_review_tasks(document_id=document_id, task_status="PENDING"):
            code = task["payload_json"].get("field_code")
            value = next((f["current_value"] for f in fields if f["field_code"] == code), None)
            self.db.resolve_review_task(task["review_task_id"], actor, value, "CONFIRM", comment)
        for field in fields:
            if field["lifecycle_stage"] != "validated":
                self.db.set_field_value(
                    document_id,
                    field["field_code"],
                    field["current_value"],
                    actor,
                    "validated",
                    "Accepted when the review was completed",
                )
        self._set_stage(doc, "validated", actor, comment or "Review completed")
        self._audit(
            doc,
            "review.completed",
            actor,
            "REVIEW_COMPLETED",
            {"fields": len(fields), "comment": comment or ""},
        )
        self._schedule_integration(doc, actor)

    def reopen_review(self, document_id: str, actor: str, reason: str) -> None:
        doc = self._document(document_id)
        self._ensure_idle(document_id)
        if doc["current_workflow_stage"] not in VALIDATED_STAGES:
            raise CommandError("INVALID_STAGE", "Only validated documents can be reopened.")
        self.db.create_review_task(
            document_id=document_id,
            queue_name=f"{doc['document_family']}_review",
            priority="normal",
            reason_codes=["manual_policy_review"],
            payload={"field_code": None, "label": "Whole document", "reason": reason},
        )
        self._set_stage(doc, REVIEW_STAGE, actor, reason or "Review reopened")
        self._audit(doc, "review.requested", actor, "REVIEW_REOPENED", {"reason": reason})

    def discard(self, document_id: str, actor: str, reason: str) -> None:
        doc = self._document(document_id)
        self._ensure_idle(document_id)
        if doc["current_workflow_stage"] == "discarded":
            raise CommandError("INVALID_STAGE", "The document is already discarded.")
        if doc["current_workflow_stage"] == "protocol_registered":
            raise CommandError(
                "INVALID_STAGE", "Registered documents cannot be discarded from the workspace."
            )
        if not (reason or "").strip():
            raise CommandError(
                "REASON_REQUIRED", "A reason is required to discard a document.", 422
            )
        self.db.cancel_review_tasks(document_id, actor, reason)
        for exc in self.db.get_exceptions(document_id=document_id, status="open"):
            self.db.resolve_exception(
                exc["exception_id"],
                {"resolved_by": actor, "comment": f"Document discarded: {reason}"},
            )
        self._set_stage(doc, "discarded", actor, reason)
        self._audit(doc, "document.discarded", actor, "DOCUMENT_DISCARDED", {"reason": reason})

    # ------------------------------------------------------------------ reprocessing

    def request_reprocessing(
        self,
        document_id: str,
        scope: str,
        actor: str,
        reason_code: str = "operator_request",
        comment: str = "",
        related_exception_id: str | None = None,
    ) -> dict:
        doc = self._document(document_id)
        if scope not in REPROCESS_SCOPES:
            raise CommandError(
                "INVALID_SCOPE", f"Scope must be one of: {', '.join(REPROCESS_SCOPES)}", 422
            )
        stage = doc["current_workflow_stage"]
        if stage == "discarded":
            raise CommandError("INVALID_STAGE", "Discarded documents cannot be reprocessed.")
        if self.queue.has_active_jobs(document_id):
            raise CommandError("BUSY", "The document is still being processed. Try again shortly.")
        job_type, owner, reset_stage = REPROCESS_SCOPES[scope]
        if scope == "extraction" and not self.db.get_document_text(document_id)["full_text"]:
            if stage in ("acquired", "failed"):
                raise CommandError("INVALID_STAGE", "Run OCR before re-running extraction.")
        if scope == "integration" and stage not in {"validated", "protocol_pending"}:
            raise CommandError(
                "INVALID_STAGE", "Only validated documents awaiting registration can be delivered."
            )

        if reset_stage:
            self.db.cancel_review_tasks(document_id, actor, f"Reprocessing requested ({scope})")
            self._set_stage(doc, reset_stage, actor, f"Reprocessing requested ({scope})")
        request_id = str(uuid.uuid4())
        self.queue.enqueue(
            job_type=job_type,
            owning_service_id=owner,
            institution_id=doc["institution_id"],
            payload={
                "document_id": document_id,
                "reprocess_request_id": request_id,
                "requested_by": actor,
                "reason_code": reason_code,
            },
            document_id=document_id,
            idempotency_scope="document",
            idempotency_key=f"{scope}:{document_id}",
            priority="high",
        )
        self._audit(
            doc,
            "workflow.reprocess_requested",
            actor,
            "REPROCESS_REQUESTED",
            {
                "request_id": request_id,
                "scope": scope,
                "reason_code": reason_code,
                "comment": comment,
            },
        )
        return {
            "schema_version": "1.0.0",
            "request_id": request_id,
            "document_id": document_id,
            "scope": scope,
            "requested_by": actor,
            "requested_at": now_utc(),
            "reason_code": reason_code,
            "comment": comment,
            "status": "accepted",
            "target_route_id": None,
            "related_exception_id": related_exception_id,
        }

    # ------------------------------------------------------------------ exceptions

    def resolve_exception(self, exception_id: str, actor: str, comment: str = "") -> dict:
        exc = self.db.get_exception(exception_id)
        if not exc:
            raise CommandError("NOT_FOUND", f"Exception {exception_id} not found", 404)
        if exc["exception_status"] == "resolved":
            raise CommandError("ALREADY_RESOLVED", "The exception is already resolved.")
        self.db.resolve_exception(
            exception_id, {"resolved_by": actor, "comment": comment, "resolved_at": now_utc()}
        )
        doc = self._document(exc["document_id"])
        self._audit(
            doc,
            "exception.resolved",
            actor,
            "EXCEPTION_RESOLVED",
            {
                "exception_id": exception_id,
                "exception_code": exc["exception_code"],
                "comment": comment,
            },
        )
        return self.db.get_exception(exception_id) or {}
