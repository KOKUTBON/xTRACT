from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import Iterator

from xtract.review.projections import VALIDATED_STAGES, now_utc, to_rfc3339
from xtract.storage.database import RuntimeDatabase

VALUE_TYPES = {"string", "text", "date", "integer", "decimal", "boolean", "identifier", "code"}
CSV_COLUMNS = [
    "document_id",
    "institution_id",
    "office_id",
    "workflow_stage",
    "document_family",
    "document_type_code",
    "source_filename",
    "source_sha256",
    "ocr_engine",
    "ocr_confidence",
    "field_code",
    "label",
    "value_type",
    "required",
    "extracted_value",
    "current_value",
    "corrected",
    "lifecycle_stage",
    "confidence_score",
    "source_page_number",
    "source_text",
    "updated_by",
    "updated_at",
]


def _typed(value: str | None, value_type: str):
    if value in (None, ""):
        return None
    try:
        if value_type == "integer":
            return int(value)
        if value_type == "decimal":
            return float(value)
    except ValueError:
        return value
    if value_type == "boolean":
        return value.strip().lower() in {"true", "yes", "1", "si", "sì"}
    return value


class DatasetExporter:
    """Exports processed documents as schema-valid records for downstream systems and research."""

    def __init__(self, database: RuntimeDatabase) -> None:
        self.db = database

    def _documents(self, stage: str = "validated", institution_id: str | None = None) -> list[dict]:
        docs = self.db.query_documents(institution_id=institution_id, limit=1_000_000)
        if stage == "validated":
            docs = [d for d in docs if d["current_workflow_stage"] in VALIDATED_STAGES]
        elif stage != "all":
            docs = [d for d in docs if d["current_workflow_stage"] == stage]
        return sorted(docs, key=lambda d: d["created_at"])

    def document_export(self, document_id: str) -> dict | None:
        """Build a validated-document-export.v1 payload for one document."""
        doc = self.db.get_document(document_id)
        if not doc:
            return None
        meta = doc["metadata_json"]
        revisions: dict[str, str] = {}
        for revision in self.db.get_field_revisions(document_id):
            revisions[revision["field_code"]] = revision["revision_id"]

        reviewed_at = [
            r["created_at"]
            for r in self.db.get_field_revisions(document_id)
            if r["lifecycle_stage"] == "validated"
        ]
        metadata = []
        for field in self.db.get_field_values(document_id):
            value_type = field["value_type"] if field["value_type"] in VALUE_TYPES else "string"
            value = field["current_value"]
            metadata.append(
                {
                    "field_code": field["field_code"],
                    "label": field["label"],
                    "value_type": value_type,
                    "lifecycle_stage": field["lifecycle_stage"],
                    "normalized_value": _typed(value, value_type),
                    "display_value": value,
                    "null_reason": "not_found" if value in (None, "") else None,
                    "confidence_score": field["confidence_score"],
                    "source_snapshot_id": revisions.get(field["field_code"], str(uuid.uuid4())),
                }
            )
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

        trace = {
            "workflow_stage": doc["current_workflow_stage"],
            "institution_id": doc["institution_id"],
            "office_id": doc["office_id"],
        }
        if reviewed_at:
            trace["last_reviewed_at"] = to_rfc3339(reviewed_at[-1])
        return {
            "schema_version": "1.0.0",
            "export_id": str(uuid.uuid4()),
            "export_stage": "validated"
            if doc["current_workflow_stage"] in VALIDATED_STAGES
            else "draft",
            "generated_at": now_utc(),
            "source_document_id": document_id,
            "source_document_version": doc.get("record_version", 1),
            "document_type": {
                "type_code": meta.get("document_type_code") or doc["document_family"],
                "display_name": meta.get("document_type_display_name") or doc["document_family"],
                "family_code": doc["document_family"],
                "taxonomy_version": "1.0.0",
                "selection_source": "system_rule",
                "confidence_score": meta.get("document_type_confidence"),
                "is_final": doc["current_workflow_stage"] in VALIDATED_STAGES,
            },
            "metadata": metadata,
            "external_references": external_references,
            "trace": trace,
        }

    def research_record(self, document_id: str, include_text: bool = False) -> dict | None:
        """Export payload plus provenance: extracted vs. operator-verified values per field."""
        export = self.document_export(document_id)
        if not export:
            return None
        doc = self.db.get_document(document_id)
        meta = doc["metadata_json"]
        record = {
            "document": export,
            "source": {
                "filename": meta.get("original_filename"),
                "mime_type": meta.get("mime_type"),
                "byte_size": meta.get("byte_size"),
                "sha256": meta.get("sha256"),
                "page_count": meta.get("page_count"),
                "ocr_engine": meta.get("ocr_selected_engine"),
                "ocr_confidence": meta.get("ocr_avg_confidence"),
            },
            "field_provenance": [
                {
                    "field_code": f["field_code"],
                    "extracted_value": f["extracted_value"],
                    "current_value": f["current_value"],
                    "corrected": f["extracted_value"] != f["current_value"],
                    "confidence_score": f["confidence_score"],
                    "source_page_number": f["source_page_number"],
                    "source_text": f["source_text"],
                    "source_bounding_box": f["source_bounding_box"],
                }
                for f in self.db.get_field_values(document_id)
            ],
        }
        if include_text:
            text = self.db.get_document_text(document_id)
            record["ocr_text"] = text["full_text"]
            record["ocr_pages"] = text["pages"]
        return record

    def iter_jsonl(
        self,
        stage: str = "validated",
        include_text: bool = False,
        institution_id: str | None = None,
    ) -> Iterator[str]:
        for doc in self._documents(stage, institution_id):
            record = self.research_record(doc["document_id"], include_text)
            if record:
                yield json.dumps(record, ensure_ascii=False) + "\n"

    def export_json(
        self, stage: str = "validated", institution_id: str | None = None
    ) -> list[dict]:
        return [
            payload
            for doc in self._documents(stage, institution_id)
            if (payload := self.document_export(doc["document_id"]))
        ]

    def export_csv(self, stage: str = "validated", institution_id: str | None = None) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for doc in self._documents(stage, institution_id):
            meta = doc["metadata_json"]
            for field in self.db.get_field_values(doc["document_id"]):
                writer.writerow(
                    {
                        "document_id": doc["document_id"],
                        "institution_id": doc["institution_id"],
                        "office_id": doc["office_id"],
                        "workflow_stage": doc["current_workflow_stage"],
                        "document_family": doc["document_family"],
                        "document_type_code": meta.get("document_type_code"),
                        "source_filename": meta.get("original_filename"),
                        "source_sha256": meta.get("sha256"),
                        "ocr_engine": meta.get("ocr_selected_engine"),
                        "ocr_confidence": meta.get("ocr_avg_confidence"),
                        "field_code": field["field_code"],
                        "label": field["label"],
                        "value_type": field["value_type"],
                        "required": field["required"],
                        "extracted_value": field["extracted_value"],
                        "current_value": field["current_value"],
                        "corrected": field["extracted_value"] != field["current_value"],
                        "lifecycle_stage": field["lifecycle_stage"],
                        "confidence_score": field["confidence_score"],
                        "source_page_number": field["source_page_number"],
                        "source_text": field["source_text"],
                        "updated_by": field["updated_by"],
                        "updated_at": field["updated_at"],
                    }
                )
        return buffer.getvalue()
