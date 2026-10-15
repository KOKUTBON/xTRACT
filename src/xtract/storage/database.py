from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class SqliteConnectionFactory:
    """Opens SQLite connections for a file database, or shares one for ``:memory:``.

    A plain ``sqlite3.connect(":memory:")`` creates a fresh, empty database on every call,
    so in-memory databases keep a single shared connection for the lifetime of the object.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = str(db_path)
        self.lock = threading.RLock()
        self._shared: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            self._shared = self._open()
        else:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            if self._shared is not None:
                try:
                    yield self._shared
                    self._shared.commit()
                except Exception:
                    self._shared.rollback()
                    raise
                return
            conn = self._open()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()


from xtract.storage.schema import SCHEMA


class RuntimeDatabase:
    """SQLite repository for documents, OCR text, fields, reviews, exceptions, and audit."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        self._factory = SqliteConnectionFactory(self.db_path)
        self._init_schema()

    def _conn(self):
        return self._factory.connect()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            for statement in SCHEMA:
                conn.execute(statement)

    # ------------------------------------------------------------------ documents

    @staticmethod
    def _document_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["metadata_json"] = _loads(data["metadata_json"], {})
        return data

    def create_document(
        self,
        institution_id: str,
        office_id: str,
        document_family: str,
        source_ingest_id: str,
        title: str | None = None,
        document_id: str | None = None,
        initial_metadata: dict | None = None,
        canonical_schema_version: str = "1.0.0",
        initial_stage: str = "acquired",
    ) -> dict:
        doc_id = document_id or str(uuid.uuid4())
        now = utc_now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO documents (
                    document_id, institution_id, office_id, document_family,
                    canonical_schema_version, current_workflow_stage, title,
                    source_ingest_id, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    institution_id,
                    office_id,
                    document_family,
                    canonical_schema_version,
                    initial_stage,
                    title,
                    source_ingest_id,
                    json.dumps(initial_metadata or {}),
                    now,
                    now,
                ),
            )
        doc = self.get_document(doc_id)
        if not doc:
            raise RuntimeError(f"Failed to create document {doc_id}")
        return doc

    def get_document(self, document_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            return self._document_row(row) if row else None

    def update_document_stage(
        self,
        document_id: str,
        workflow_stage: str,
        metadata_update: dict | None = None,
        document_family: str | None = None,
    ) -> bool:
        now = utc_now_iso()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT metadata_json, document_family FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if not row:
                return False
            metadata = _loads(row["metadata_json"], {})
            if metadata_update:
                metadata.update(metadata_update)
            conn.execute(
                """
                UPDATE documents
                SET current_workflow_stage = ?,
                    metadata_json = ?,
                    document_family = ?,
                    updated_at = ?,
                    record_version = record_version + 1
                WHERE document_id = ?
                """,
                (
                    workflow_stage,
                    json.dumps(metadata),
                    document_family or row["document_family"],
                    now,
                    document_id,
                ),
            )
            return True

    def query_documents(
        self,
        text_query: str | None = None,
        workflow_stage: str | None = None,
        institution_id: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        query = "SELECT d.* FROM documents d WHERE 1=1"
        params: list[Any] = []
        if institution_id:
            query += " AND d.institution_id = ?"
            params.append(institution_id)
        if workflow_stage:
            query += " AND d.current_workflow_stage = ?"
            params.append(workflow_stage)
        if text_query:
            like = f"%{text_query}%"
            query += """
                AND (
                    d.title LIKE ? OR d.metadata_json LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM document_texts t
                        WHERE t.document_id = d.document_id AND t.full_text LIKE ?
                    )
                    OR EXISTS (
                        SELECT 1 FROM field_values f
                        WHERE f.document_id = d.document_id AND f.current_value LIKE ?
                    )
                )
            """
            params.extend([like, like, like, like])
        query += " ORDER BY d.created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            return [self._document_row(row) for row in conn.execute(query, params).fetchall()]

    def count_documents_by_stage(self, institution_id: str | None = None) -> dict[str, int]:
        query = "SELECT current_workflow_stage AS stage, COUNT(*) AS total FROM documents"
        params = []
        if institution_id is not None:
            query += " WHERE institution_id = ?"
            params.append(institution_id)
        with self._conn() as conn:
            rows = conn.execute(query + " GROUP BY current_workflow_stage", params).fetchall()
            return {row["stage"]: row["total"] for row in rows}

    def find_document_by_sha256(self, institution_id: str, sha256: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT d.* FROM documents d
                JOIN document_blob_objects b ON b.document_id = d.document_id
                WHERE b.blob_class = 'source' AND b.sha256 = ? AND d.institution_id = ?
                  AND d.current_workflow_stage != 'discarded'
                ORDER BY d.created_at ASC LIMIT 1
                """,
                (sha256, institution_id),
            ).fetchone()
            return self._document_row(row) if row else None

    # ------------------------------------------------------------------ OCR text

    def save_document_text(self, document_id: str, full_text: str, pages: list[dict]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO document_texts (document_id, full_text, pages_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    full_text = excluded.full_text,
                    pages_json = excluded.pages_json,
                    updated_at = excluded.updated_at
                """,
                (document_id, full_text, json.dumps(pages), utc_now_iso()),
            )

    def get_document_text(self, document_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT full_text, pages_json FROM document_texts WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if not row:
                return {"full_text": "", "pages": []}
            return {"full_text": row["full_text"], "pages": _loads(row["pages_json"], [])}

    # ------------------------------------------------------------------ blobs

    def record_blob_object(
        self,
        document_id: str,
        bucket_name: str,
        object_key: str,
        blob_class: str,
        content_type: str,
        sha256: str,
        byte_size: int,
        retention_profile: str = "standard_retention",
    ) -> dict:
        blob_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO document_blob_objects (
                    blob_id, document_id, bucket_name, object_key,
                    blob_class, content_type, sha256, byte_size,
                    retention_profile, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bucket_name, object_key) DO UPDATE SET
                    sha256 = excluded.sha256,
                    byte_size = excluded.byte_size,
                    created_at = excluded.created_at
                """,
                (
                    blob_id,
                    document_id,
                    bucket_name,
                    object_key,
                    blob_class,
                    content_type,
                    sha256,
                    byte_size,
                    retention_profile,
                    now,
                ),
            )
        return {
            "blob_id": blob_id,
            "document_id": document_id,
            "bucket_name": bucket_name,
            "object_key": object_key,
            "blob_class": blob_class,
            "content_type": content_type,
            "sha256": sha256,
            "byte_size": byte_size,
            "created_at": now,
        }

    def get_blob_objects(self, document_id: str, blob_class: str | None = None) -> list[dict]:
        query = "SELECT * FROM document_blob_objects WHERE document_id = ?"
        params: list[Any] = [document_id]
        if blob_class:
            query += " AND blob_class = ?"
            params.append(blob_class)
        query += " ORDER BY created_at ASC"
        with self._conn() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    # ------------------------------------------------------------------ audit

    def record_audit_event(
        self,
        event_type: str,
        institution_id: str,
        document_id: str | None,
        actor_type: str,
        actor_id: str,
        action_code: str,
        payload: dict | None = None,
        trace_id: str | None = None,
    ) -> dict:
        event_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    audit_event_id, event_type, institution_id, document_id,
                    actor_type, actor_id, action_code, trace_id,
                    payload_json, event_timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    institution_id,
                    document_id,
                    actor_type,
                    actor_id,
                    action_code,
                    trace_id or str(uuid.uuid4()),
                    json.dumps(payload or {}),
                    now,
                    now,
                ),
            )
        return {
            "audit_event_id": event_id,
            "event_type": event_type,
            "institution_id": institution_id,
            "document_id": document_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action_code": action_code,
            "event_timestamp": now,
        }

    def get_audit_events(self, document_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE document_id = ? "
                "ORDER BY event_timestamp ASC, rowid ASC",
                (document_id,),
            ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["payload_json"] = _loads(item.get("payload_json"), {})
            events.append(item)
        return events

    # ------------------------------------------------------------------ review tasks

    @staticmethod
    def _task_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["reason_codes"] = _loads(data["reason_codes"], [])
        data["payload_json"] = _loads(data["payload_json"], {})
        return data

    def create_review_task(
        self,
        document_id: str,
        queue_name: str,
        priority: str,
        reason_codes: list[str],
        payload: dict,
        assigned_role: str | None = "operator",
        assigned_user_id: str | None = None,
        task_id: str | None = None,
    ) -> dict:
        task_id = task_id or str(uuid.uuid4())
        now = utc_now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO review_tasks (
                    review_task_id, document_id, queue_name, task_status,
                    priority, assigned_role, assigned_user_id, reason_codes,
                    payload_json, opened_at, created_at, updated_at
                ) VALUES (?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    document_id,
                    queue_name,
                    priority,
                    assigned_role,
                    assigned_user_id,
                    json.dumps(reason_codes),
                    json.dumps(payload),
                    now,
                    now,
                    now,
                ),
            )
        task = self.get_review_task(task_id)
        if not task:
            raise RuntimeError(f"Failed to create review task {task_id}")
        return task

    def get_review_task(self, review_task_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM review_tasks WHERE review_task_id = ?", (review_task_id,)
            ).fetchone()
            return self._task_row(row) if row else None

    def get_review_tasks(
        self,
        document_id: str | None = None,
        task_status: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM review_tasks WHERE 1=1"
        params: list[Any] = []
        if document_id:
            query += " AND document_id = ?"
            params.append(document_id)
        if task_status:
            query += " AND task_status = ?"
            params.append(task_status)
        query += " ORDER BY opened_at ASC, rowid ASC"
        with self._conn() as conn:
            return [self._task_row(row) for row in conn.execute(query, params).fetchall()]

    def resolve_review_task(
        self,
        review_task_id: str,
        reviewer_user_id: str,
        final_value: Any,
        action: str = "CONFIRM",
        comment: str | None = None,
        status: str = "RESOLVED",
    ) -> bool:
        now = utc_now_iso()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM review_tasks WHERE review_task_id = ?",
                (review_task_id,),
            ).fetchone()
            if not row:
                return False
            payload = _loads(row["payload_json"], {})
            payload.update(
                {
                    "final_value": final_value,
                    "resolution_action": action,
                    "resolved_by": reviewer_user_id,
                    "resolved_at": now,
                }
            )
            if comment:
                payload["comment"] = comment
            conn.execute(
                """
                UPDATE review_tasks
                SET task_status = ?, assigned_user_id = ?, payload_json = ?,
                    completed_at = ?, updated_at = ?, lock_version = lock_version + 1
                WHERE review_task_id = ?
                """,
                (status, reviewer_user_id, json.dumps(payload), now, now, review_task_id),
            )
            return True

    def cancel_review_tasks(self, document_id: str, actor_id: str, reason: str) -> int:
        cancelled = 0
        for task in self.get_review_tasks(document_id=document_id, task_status="PENDING"):
            self.resolve_review_task(
                task["review_task_id"],
                reviewer_user_id=actor_id,
                final_value=None,
                action="CANCEL",
                comment=reason,
                status="CANCELLED",
            )
            cancelled += 1
        return cancelled

    # ------------------------------------------------------------------ fields

    @staticmethod
    def _field_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["required"] = bool(data["required"])
        data["review_required"] = bool(data["review_required"])
        data["review_reason_codes"] = _loads(data["review_reason_codes"], [])
        data["source_bounding_box"] = _loads(data["source_bounding_box"], None)
        return data

    def replace_field_values(
        self,
        document_id: str,
        extraction_run_id: str,
        field_results: list[dict],
        actor_id: str,
    ) -> None:
        """Replace all field values of a document with a new extraction run."""
        now = utc_now_iso()
        with self._conn() as conn:
            conn.execute("DELETE FROM field_values WHERE document_id = ?", (document_id,))
            for position, field in enumerate(field_results):
                value = field.get("normalized_value")
                value = None if value is None else str(value)
                conn.execute(
                    """
                    INSERT INTO field_values (
                        document_id, field_code, label, value_type, required, position,
                        extracted_value, current_value, confidence_score, review_required,
                        review_reason_codes, lifecycle_stage, source_page_number, source_text,
                        source_bounding_box, extraction_run_id, updated_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        field["field_code"],
                        field["label"],
                        field["value_type"],
                        int(bool(field.get("required"))),
                        position,
                        value,
                        value,
                        field.get("confidence_score"),
                        int(bool(field.get("review_required"))),
                        json.dumps(field.get("review_reason_codes", [])),
                        field.get("source_page_number"),
                        field.get("source_text"),
                        json.dumps(field.get("source_bounding_box")),
                        extraction_run_id,
                        actor_id,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO field_revisions (
                        revision_id, document_id, field_code, lifecycle_stage,
                        value, actor_id, note, created_at
                    ) VALUES (?, ?, ?, 'extracted', ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        document_id,
                        field["field_code"],
                        value,
                        actor_id,
                        f"Extraction run {extraction_run_id}",
                        now,
                    ),
                )

    def get_field_values(self, document_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM field_values WHERE document_id = ? ORDER BY position ASC",
                (document_id,),
            ).fetchall()
            return [self._field_row(row) for row in rows]

    def get_field_value(self, document_id: str, field_code: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM field_values WHERE document_id = ? AND field_code = ?",
                (document_id, field_code),
            ).fetchone()
            return self._field_row(row) if row else None

    def set_field_value(
        self,
        document_id: str,
        field_code: str,
        value: str | None,
        actor_id: str,
        lifecycle_stage: str = "validated",
        note: str | None = None,
    ) -> dict | None:
        now = utc_now_iso()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE field_values
                SET current_value = ?, lifecycle_stage = ?, review_required = 0,
                    review_reason_codes = '[]', updated_by = ?, updated_at = ?
                WHERE document_id = ? AND field_code = ?
                """,
                (value, lifecycle_stage, actor_id, now, document_id, field_code),
            )
            if cur.rowcount == 0:
                return None
            conn.execute(
                """
                INSERT INTO field_revisions (
                    revision_id, document_id, field_code, lifecycle_stage,
                    value, actor_id, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    document_id,
                    field_code,
                    lifecycle_stage,
                    value,
                    actor_id,
                    note,
                    now,
                ),
            )
        return self.get_field_value(document_id, field_code)

    def get_field_revisions(self, document_id: str, field_code: str | None = None) -> list[dict]:
        query = "SELECT * FROM field_revisions WHERE document_id = ?"
        params: list[Any] = [document_id]
        if field_code:
            query += " AND field_code = ?"
            params.append(field_code)
        query += " ORDER BY created_at ASC, rowid ASC"
        with self._conn() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    # ------------------------------------------------------------------ external references

    def record_external_reference(
        self,
        document_id: str,
        target_system: str,
        reference_type: str,
        authoritative_value: str,
        sync_status: str = "synchronized",
        metadata: dict | None = None,
        synced_at: str | None = None,
        reference_id: str | None = None,
    ) -> dict:
        ext_ref_id = reference_id or str(uuid.uuid4())
        now = utc_now_iso()
        timestamp = synced_at or now
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO external_references (
                    external_reference_id, document_id, target_system, reference_type,
                    authoritative_value, sync_status, metadata_json, synced_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id, target_system, reference_type) DO UPDATE SET
                    authoritative_value = excluded.authoritative_value,
                    sync_status = excluded.sync_status,
                    metadata_json = excluded.metadata_json,
                    synced_at = excluded.synced_at,
                    updated_at = excluded.updated_at,
                    lock_version = lock_version + 1
                """,
                (
                    ext_ref_id,
                    document_id,
                    target_system,
                    reference_type,
                    authoritative_value,
                    sync_status,
                    json.dumps(metadata or {}),
                    timestamp,
                    now,
                    now,
                ),
            )
        return {
            "external_reference_id": ext_ref_id,
            "document_id": document_id,
            "target_system": target_system,
            "reference_type": reference_type,
            "authoritative_value": authoritative_value,
            "sync_status": sync_status,
            "metadata_json": metadata or {},
            "synced_at": timestamp,
        }

    def get_external_references(self, document_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM external_references WHERE document_id = ? ORDER BY created_at ASC",
                (document_id,),
            ).fetchall()
        refs = []
        for row in rows:
            item = dict(row)
            item["metadata_json"] = _loads(item["metadata_json"], {})
            refs.append(item)
        return refs

    def next_sequence_value(self, sequence_key: str) -> int:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO registry_sequences (sequence_key, last_value) VALUES (?, 1)
                ON CONFLICT(sequence_key) DO UPDATE SET last_value = last_value + 1
                """,
                (sequence_key,),
            )
            row = conn.execute(
                "SELECT last_value FROM registry_sequences WHERE sequence_key = ?",
                (sequence_key,),
            ).fetchone()
            return int(row["last_value"])

    # ------------------------------------------------------------------ exceptions

    @staticmethod
    def _exception_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["payload_json"] = _loads(data["payload_json"], {})
        return data

    def record_exception(
        self,
        document_id: str,
        exception_code: str,
        severity: str,
        exception_status: str = "open",
        source_service: str = "system",
        payload: dict | None = None,
        exception_id: str | None = None,
    ) -> dict:
        """Record an exception, refreshing an open exception with the same code if present."""
        now = utc_now_iso()
        with self._conn() as conn:
            existing = conn.execute(
                """
                SELECT exception_id FROM document_exceptions
                WHERE document_id = ? AND exception_code = ? AND exception_status = 'open'
                """,
                (document_id, exception_code),
            ).fetchone()
            if existing and exception_status == "open":
                exc_id = existing["exception_id"]
                conn.execute(
                    """
                    UPDATE document_exceptions
                    SET payload_json = ?, severity = ?, last_seen_at = ?, updated_at = ?,
                        lock_version = lock_version + 1
                    WHERE exception_id = ?
                    """,
                    (json.dumps(payload or {}), severity, now, now, exc_id),
                )
            else:
                exc_id = exception_id or str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO document_exceptions (
                        exception_id, document_id, exception_code, severity,
                        exception_status, source_service, payload_json,
                        first_seen_at, last_seen_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        exc_id,
                        document_id,
                        exception_code,
                        severity,
                        exception_status,
                        source_service,
                        json.dumps(payload or {}),
                        now,
                        now,
                        now,
                        now,
                    ),
                )
        return self.get_exception(exc_id) or {}

    def get_exception(self, exception_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM document_exceptions WHERE exception_id = ?", (exception_id,)
            ).fetchone()
            return self._exception_row(row) if row else None

    def get_exceptions(
        self,
        document_id: str | None = None,
        status: str | None = None,
        institution_id: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM document_exceptions WHERE 1=1"
        params: list[Any] = []
        if institution_id is not None:
            query += (
                " AND document_id IN (SELECT document_id FROM documents WHERE institution_id = ?)"
            )
            params.append(institution_id)
        if document_id:
            query += " AND document_id = ?"
            params.append(document_id)
        if status:
            query += " AND exception_status = ?"
            params.append(status)
        query += " ORDER BY first_seen_at DESC, rowid DESC"
        with self._conn() as conn:
            return [self._exception_row(row) for row in conn.execute(query, params).fetchall()]

    def resolve_exception(self, exception_id: str, resolution: dict | None = None) -> bool:
        now = utc_now_iso()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM document_exceptions WHERE exception_id = ?",
                (exception_id,),
            ).fetchone()
            if not row:
                return False
            payload = _loads(row["payload_json"], {})
            if resolution:
                payload["resolution"] = resolution
            conn.execute(
                """
                UPDATE document_exceptions
                SET exception_status = 'resolved', resolved_at = ?, updated_at = ?,
                    payload_json = ?, lock_version = lock_version + 1
                WHERE exception_id = ?
                """,
                (now, now, json.dumps(payload), exception_id),
            )
            return True

    def resolve_open_exceptions(
        self, document_id: str, exception_codes: list[str], resolution: dict | None = None
    ) -> int:
        resolved = 0
        for exc in self.get_exceptions(document_id=document_id, status="open"):
            if exc["exception_code"] in exception_codes:
                resolved += int(self.resolve_exception(exc["exception_id"], resolution))
        return resolved
