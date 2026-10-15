from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from xtract.integration.connector import (
    CONNECTOR_REGISTRY,
    HttpProtocolConnector,
    LocalRegistryConnector,
    ProtocolConnector,
)

logger = logging.getLogger("protocol-dispatcher")

WILDCARD_FAMILY = "*"
MAX_BACKOFF_SECONDS = 10


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load(source: dict | Path) -> dict:
    return json.loads(source.read_text(encoding="utf-8")) if isinstance(source, Path) else source


class ProtocolDispatcher:
    """Builds protocol commands from policy routes and delivers them through connectors."""

    def __init__(
        self,
        connector_catalog: dict | Path,
        integration_policy: dict | Path,
        database=None,
        connectors: dict[str, ProtocolConnector] | None = None,
        sleep=time.sleep,
    ) -> None:
        self.catalog = _load(connector_catalog)
        self.policy = _load(integration_policy)
        self.sleep = sleep
        self.connectors: dict[str, ProtocolConnector] = {}
        for connector in self.catalog.get("connectors", []):
            cid = connector["connector_id"]
            ctype = connector.get("channel_type", "http_api")
            if ctype in ("local_registry", "agid_protocollo", "peppol_registry"):
                cls = CONNECTOR_REGISTRY.get(ctype, LocalRegistryConnector)
                if database is not None:
                    self.connectors[cid] = cls(database=database)
                else:
                    self.connectors[cid] = cls()
            elif ctype in CONNECTOR_REGISTRY:
                self.connectors[cid] = CONNECTOR_REGISTRY[ctype]()
            else:
                self.connectors[cid] = HttpProtocolConnector()
        self.connectors.update(connectors or {})

    def available_connectors(self) -> list[dict]:
        """Return public status and channel information for all configured connectors."""
        return [
            {
                "connector_id": c["connector_id"],
                "system_name": c["system_name"],
                "description": c["description"],
                "channel_type": c["channel_type"],
                "status": c.get("status", "active"),
                "supported_commands": c.get("supported_commands", ["protocol.register"]),
                "reference_prefix": c.get("reference_prefix"),
                "ownership": c.get("ownership", {}),
            }
            for c in self.catalog.get("connectors", [])
        ]

    def get_connector(self, connector_id: str) -> dict:
        for connector in self.catalog.get("connectors", []):
            if connector.get("connector_id") == connector_id:
                return connector
        raise ValueError(f"Connector {connector_id} not found in connector catalog")

    def get_route(self, document_family: str, workflow_stage: str = "validated") -> dict | None:
        fallback = None
        for route in self.policy.get("routes", []):
            if not route.get("enabled", True):
                continue
            if route.get("trigger_workflow_stage") != workflow_stage:
                continue
            connector_id = route.get("target_connector_id")
            try:
                if self.get_connector(connector_id).get("status", "active") != "active":
                    continue
            except ValueError:
                continue
            if route.get("document_family") == document_family:
                return route
            if route.get("document_family") == WILDCARD_FAMILY and fallback is None:
                fallback = route
        return fallback

    def get_retry_profile(self, profile_id: str) -> dict:
        for profile in self.policy.get("retry_profiles", []):
            if profile.get("profile_id") == profile_id:
                return profile
        return {"max_attempts": 3, "backoff_seconds": 2, "retryable_error_codes": []}

    def build_command(
        self,
        document: dict,
        fields: list[dict],
        route: dict,
        connector: dict,
        initiated_by: str = "service:integration-hub",
    ) -> dict:
        values = {field["field_code"]: field.get("current_value") for field in fields}
        mapping = route.get("field_mapping") or [
            {"field_code": code, "target_name": code, "required": False} for code in values
        ]
        metadata = [
            {
                "field_code": item["field_code"],
                "target_name": item["target_name"],
                "required": item.get("required", False),
                "value": values.get(item["field_code"]),
            }
            for item in mapping
        ]
        meta = document["metadata_json"]
        command_type = route.get("command_type", "protocol.register")
        document_id = document["document_id"]
        return {
            "schema_version": "1.0.0",
            "command_id": str(uuid.uuid4()),
            "command_type": command_type,
            "connector_id": connector["connector_id"],
            "generated_at": now_utc(),
            "document_id": document_id,
            "idempotency_key": f"{document_id}:{command_type}:{connector['connector_id']}",
            "source_export": {
                "export_id": str(uuid.uuid4()),
                "export_stage": "validated",
                "source_document_id": document_id,
                "source_document_version": document.get("record_version", 1),
                "path": f"api/v1/documents/{document_id}/export",
            },
            "caller": {
                "institution_id": document["institution_id"],
                "office_id": document["office_id"],
                "service_name": "service:integration-hub",
            },
            "ownership": {
                "source_of_truth_fields": route.get("sync_contract", {}).get(
                    "source_of_truth_fields", []
                ),
                "target_of_truth_fields": route.get("sync_contract", {}).get(
                    "target_of_truth_fields", []
                ),
                "synchronization_owner": route.get("sync_contract", {}).get(
                    "synchronization_owner", "integration-hub"
                ),
            },
            "audit_context": {
                "correlation_id": str(uuid.uuid4()),
                "initiated_by": initiated_by,
                "reason": f"Route {route.get('route_id')} triggered by document validation",
            },
            "payload": {
                "document_type_code": meta.get("document_type_code", document["document_family"]),
                "document_type_name": meta.get(
                    "document_type_display_name", document["document_family"]
                ),
                "source_filename": meta.get("original_filename", document.get("title") or ""),
                "checksum_sha256": meta.get("sha256") or "0" * 64,
                "requested_reference_type": route.get(
                    "authoritative_reference_type", "protocol_id"
                ),
                "metadata": metadata,
            },
        }

    def missing_required_values(self, command: dict) -> list[str]:
        return [
            item["field_code"]
            for item in command["payload"]["metadata"]
            if item["required"] and item["value"] in (None, "")
        ]

    def dispatch_command(
        self, command: dict, connector_id: str, retry_profile_id: str = ""
    ) -> tuple[dict | None, list[dict], str]:
        """Deliver a command with retries. Returns (response, attempts, final_status)."""
        connector_def = self.get_connector(connector_id)
        connector = self.connectors.get(connector_id)
        profile = self.get_retry_profile(retry_profile_id)
        max_attempts = max(1, int(profile.get("max_attempts", 3)))
        backoff = float(profile.get("backoff_seconds", 2))
        correlation_id = command["audit_context"]["correlation_id"]

        attempts: list[dict] = []
        for attempt_number in range(1, max_attempts + 1):
            started_at = now_utc()
            if connector is None:
                outcome = {
                    "mode": "permanent_failure",
                    "http_status": None,
                    "error_code": "connector_unavailable",
                    "response": None,
                }
            else:
                outcome = connector.dispatch(command, connector_def, attempt_number)
            response = outcome.get("response")
            attempts.append(
                {
                    "attempt_number": attempt_number,
                    "started_at": started_at,
                    "completed_at": now_utc(),
                    "result": outcome.get("mode", "permanent_failure"),
                    "error_code": outcome.get("error_code"),
                    "http_status": outcome.get("http_status"),
                    "audit_correlation_id": correlation_id,
                    "remote_reference_id": (response or {})
                    .get("remote_reference", {})
                    .get("reference_id"),
                }
            )
            if outcome.get("mode") == "success":
                return response, attempts, "synchronized"
            if outcome.get("mode") != "retryable_failure":
                break
            if attempt_number < max_attempts:
                self.sleep(min(backoff * attempt_number, MAX_BACKOFF_SECONDS))
        return None, attempts, "failed"
