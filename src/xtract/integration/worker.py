from __future__ import annotations

import json
import logging
import uuid

from xtract.integration.dispatcher import ProtocolDispatcher, now_utc
from xtract.storage.database import RuntimeDatabase
from xtract.storage.queue import Job, JobQueue
from xtract.storage.storage import ObjectStorageClient

logger = logging.getLogger("integration-worker")

DISPATCHABLE_STAGES = {"validated", "protocol_pending"}


class IntegrationWorker:
    """Executes integration.dispatch_protocol jobs and reconciles remote references."""

    def __init__(
        self,
        queue: JobQueue,
        database: RuntimeDatabase,
        storage: ObjectStorageClient,
        dispatcher: ProtocolDispatcher,
    ) -> None:
        self.queue = queue
        self.db = database
        self.storage = storage
        self.dispatcher = dispatcher

    def _put_json(self, key: str, payload: dict) -> str:
        self.storage.put_object(
            "integration-artifacts",
            key,
            json.dumps(payload, indent=2).encode("utf-8"),
            "application/json",
        )
        return f"integration-artifacts/{key}"

    def process_job(self, job: Job) -> dict:
        document_id = job.payload.get("document_id") or job.document_id
        requested_by = job.payload.get("requested_by", "integration-hub")
        doc = self.db.get_document(document_id)
        if not doc:
            raise ValueError(f"Document {document_id} does not exist")
        if doc["current_workflow_stage"] not in DISPATCHABLE_STAGES:
            return {
                "document_id": document_id,
                "status": "skipped",
                "reason": f"Stage {doc['current_workflow_stage']} is not dispatchable",
            }

        route = self.dispatcher.get_route(doc["document_family"], "validated")
        if not route:
            return {
                "document_id": document_id,
                "status": "skipped",
                "reason": f"No active integration route for family {doc['document_family']}",
            }

        institution_id = doc["institution_id"]
        connector_id = route["target_connector_id"]
        connector_def = self.dispatcher.get_connector(connector_id)
        system_name = connector_def.get("system_name", connector_id)
        reference_type = route.get("authoritative_reference_type", "protocol_id")

        existing = next(
            (
                ref
                for ref in self.db.get_external_references(document_id)
                if ref["target_system"] == system_name
                and ref["reference_type"] == reference_type
                and ref["sync_status"] == "synchronized"
            ),
            None,
        )
        if existing:
            # Registration is idempotent: a document keeps the reference it was first given.
            self.db.update_document_stage(
                document_id,
                "protocol_registered",
                {"registration_reference": existing["authoritative_value"]},
            )
            self.db.record_audit_event(
                event_type="protocol.registered",
                institution_id=institution_id,
                document_id=document_id,
                actor_type="service",
                actor_id="integration-hub",
                action_code="PROTOCOL_REFERENCE_REUSED",
                payload={
                    "reference_id": existing["authoritative_value"],
                    "connector_id": connector_id,
                },
            )
            return {
                "document_id": document_id,
                "status": "synchronized",
                "remote_reference_id": existing["authoritative_value"],
                "reused": True,
            }
        fields = self.db.get_field_values(document_id)
        command = self.dispatcher.build_command(
            doc, fields, route, connector_def, initiated_by=requested_by
        )
        prefix = f"{institution_id}/{document_id}"
        self._put_json(f"{prefix}/commands/{command['command_id']}.json", command)

        self.db.update_document_stage(document_id, "protocol_pending")
        self.db.record_audit_event(
            event_type="protocol.requested",
            institution_id=institution_id,
            document_id=document_id,
            actor_type="service",
            actor_id="integration-hub",
            action_code="PROTOCOL_REQUESTED",
            payload={
                "command_id": command["command_id"],
                "connector_id": connector_id,
                "route_id": route["route_id"],
            },
        )

        missing = self.dispatcher.missing_required_values(command)
        if missing:
            response, final_status = None, "failed"
            attempts = [
                {
                    "attempt_number": 1,
                    "started_at": now_utc(),
                    "completed_at": now_utc(),
                    "result": "permanent_failure",
                    "error_code": "required_values_missing",
                    "http_status": None,
                    "audit_correlation_id": command["audit_context"]["correlation_id"],
                    "remote_reference_id": None,
                }
            ]
        else:
            response, attempts, final_status = self.dispatcher.dispatch_command(
                command, connector_id, route.get("retry_profile_id", "")
            )

        response_path = None
        if response:
            response_path = self._put_json(
                f"{prefix}/responses/{command['command_id']}.response.json", response
            )

        run_id = str(uuid.uuid4())
        delivery_report = {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "connector_id": connector_id,
            "generated_at": now_utc(),
            "deliveries": [
                {
                    "document_id": document_id,
                    "command_id": command["command_id"],
                    "final_status": final_status,
                    "attempts": attempts,
                    "response_path": response_path,
                    "updated_document_path": None,
                }
            ],
            "summary": {
                "synchronized_count": int(final_status == "synchronized"),
                "failed_count": int(final_status == "failed"),
                "skipped_count": 0,
            },
        }
        delivery_path = self._put_json(f"{prefix}/delivery-reports/{run_id}.json", delivery_report)

        owner = connector_def.get("ownership", {}).get("target_system_of_record", system_name)
        if final_status == "synchronized":
            remote = response["remote_reference"]
            self.db.record_external_reference(
                document_id=document_id,
                target_system=system_name,
                reference_type=remote["reference_type"],
                authoritative_value=remote["reference_id"],
                sync_status="synchronized",
                metadata={
                    "uri": remote.get("uri"),
                    "connector_id": connector_id,
                    "command_id": command["command_id"],
                    "run_id": run_id,
                },
                synced_at=remote.get("synchronized_at"),
            )
            self.db.update_document_stage(
                document_id,
                "protocol_registered",
                {"registration_reference": remote["reference_id"]},
            )
            self.db.resolve_open_exceptions(
                document_id,
                ["protocol_system_unavailable"],
                {"resolved_by": "integration-hub", "reason": "Delivery succeeded"},
            )
            self.db.record_audit_event(
                event_type="protocol.registered",
                institution_id=institution_id,
                document_id=document_id,
                actor_type="service",
                actor_id="integration-hub",
                action_code="PROTOCOL_REGISTERED",
                payload={"reference_id": remote["reference_id"], "connector_id": connector_id},
            )
            recon_item = {
                "document_id": document_id,
                "command_id": command["command_id"],
                "reference_type": remote["reference_type"],
                "remote_reference_id": remote["reference_id"],
                "delivery_status": "synchronized",
                "reconciliation_status": "matched",
                "local_document_update": "applied",
                "owner_of_truth": owner,
                "notes": "Remote reference synchronized and recorded locally.",
            }
            recon_summary = {"matched_count": 1, "missing_count": 0, "not_applicable_count": 0}
        else:
            last = attempts[-1]
            message = (
                f"Required values missing for delivery: {', '.join(missing)}."
                if missing
                else f"Delivery to {system_name} failed after {len(attempts)} attempt(s) "
                f"(last error: {last.get('error_code') or 'unknown'})."
            )
            self.db.record_exception(
                document_id=document_id,
                exception_code="protocol_system_unavailable",
                severity="high",
                source_service="integration-hub",
                payload={
                    "message": message,
                    "connector_id": connector_id,
                    "error_code": last.get("error_code"),
                    "delivery_report_path": delivery_path,
                },
            )
            self.db.record_audit_event(
                event_type="protocol.failed",
                institution_id=institution_id,
                document_id=document_id,
                actor_type="service",
                actor_id="integration-hub",
                action_code="PROTOCOL_FAILED",
                payload={"connector_id": connector_id, "error_code": last.get("error_code")},
            )
            recon_item = {
                "document_id": document_id,
                "command_id": command["command_id"],
                "reference_type": route.get("authoritative_reference_type", "protocol_id"),
                "remote_reference_id": None,
                "delivery_status": "failed",
                "reconciliation_status": "missing",
                "local_document_update": "failed",
                "owner_of_truth": owner,
                "notes": message,
            }
            recon_summary = {"matched_count": 0, "missing_count": 1, "not_applicable_count": 0}

        reconciliation_report = {
            "schema_version": "1.0.0",
            "report_id": run_id,
            "connector_id": connector_id,
            "generated_at": now_utc(),
            "items": [recon_item],
            "summary": recon_summary,
        }
        recon_path = self._put_json(
            f"{prefix}/reconciliation-reports/{run_id}.json", reconciliation_report
        )
        return {
            "run_id": run_id,
            "document_id": document_id,
            "status": final_status,
            "remote_reference_id": recon_item["remote_reference_id"],
            "delivery_report_path": delivery_path,
            "reconciliation_report_path": recon_path,
        }
