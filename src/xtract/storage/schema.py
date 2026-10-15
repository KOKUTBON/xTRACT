"""SQLite database schema definitions and indexes for xTRACT."""

from __future__ import annotations

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS documents (
        document_id TEXT PRIMARY KEY,
        institution_id TEXT NOT NULL,
        office_id TEXT NOT NULL,
        document_family TEXT NOT NULL,
        canonical_schema_version TEXT NOT NULL,
        current_workflow_stage TEXT NOT NULL,
        title TEXT,
        source_ingest_id TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        latest_revision_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        record_version INTEGER NOT NULL DEFAULT 1,
        lock_version INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_texts (
        document_id TEXT PRIMARY KEY,
        full_text TEXT NOT NULL DEFAULT '',
        pages_json TEXT NOT NULL DEFAULT '[]',
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_blob_objects (
        blob_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        bucket_name TEXT NOT NULL,
        object_key TEXT NOT NULL,
        blob_class TEXT NOT NULL,
        content_type TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        byte_size INTEGER NOT NULL,
        immutable_write INTEGER NOT NULL DEFAULT 1,
        retention_profile TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (bucket_name, object_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        audit_event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        institution_id TEXT NOT NULL,
        document_id TEXT,
        actor_type TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        action_code TEXT NOT NULL,
        trace_id TEXT,
        payload_json TEXT NOT NULL DEFAULT '{}',
        event_timestamp TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_tasks (
        review_task_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        queue_name TEXT NOT NULL,
        task_status TEXT NOT NULL,
        priority TEXT NOT NULL,
        assigned_role TEXT,
        assigned_user_id TEXT,
        reason_codes TEXT NOT NULL DEFAULT '[]',
        payload_json TEXT NOT NULL DEFAULT '{}',
        opened_at TEXT NOT NULL,
        due_at TEXT,
        completed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        lock_version INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS external_references (
        external_reference_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        target_system TEXT NOT NULL,
        reference_type TEXT NOT NULL,
        authoritative_value TEXT NOT NULL,
        sync_status TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        synced_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        lock_version INTEGER NOT NULL DEFAULT 0,
        UNIQUE (document_id, target_system, reference_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_exceptions (
        exception_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        exception_code TEXT NOT NULL,
        severity TEXT NOT NULL,
        exception_status TEXT NOT NULL,
        source_service TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        resolved_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        lock_version INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS field_values (
        document_id TEXT NOT NULL,
        field_code TEXT NOT NULL,
        label TEXT NOT NULL,
        value_type TEXT NOT NULL,
        required INTEGER NOT NULL DEFAULT 0,
        position INTEGER NOT NULL DEFAULT 0,
        extracted_value TEXT,
        current_value TEXT,
        confidence_score REAL,
        review_required INTEGER NOT NULL DEFAULT 0,
        review_reason_codes TEXT NOT NULL DEFAULT '[]',
        lifecycle_stage TEXT NOT NULL DEFAULT 'extracted',
        source_page_number INTEGER,
        source_text TEXT,
        source_bounding_box TEXT,
        extraction_run_id TEXT,
        updated_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (document_id, field_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS field_revisions (
        revision_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        field_code TEXT NOT NULL,
        lifecycle_stage TEXT NOT NULL,
        value TEXT,
        actor_id TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS registry_sequences (
        sequence_key TEXT PRIMARY KEY,
        last_value INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_document ON audit_events (document_id, event_timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_review_document ON review_tasks (document_id, task_status)",
    "CREATE INDEX IF NOT EXISTS idx_exceptions_document ON document_exceptions (document_id)",
    "CREATE INDEX IF NOT EXISTS idx_blobs_sha ON document_blob_objects (sha256)",
    "CREATE INDEX IF NOT EXISTS idx_revisions_field ON field_revisions (document_id, field_code)",
]
