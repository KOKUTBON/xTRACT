from __future__ import annotations

import abc
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xtract.storage.database import SqliteConnectionFactory


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    job_id: str
    job_type: str
    owning_service_id: str
    institution_id: str
    document_id: str | None
    idempotency_scope: str
    idempotency_key: str
    priority: str
    status: str
    visible_at: str
    attempts: int
    max_attempts: int
    concurrency_key: str | None
    payload: dict
    result: dict | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self, include_payload: bool = False) -> dict:
        data = asdict(self)
        if not include_payload:
            data.pop("payload", None)
            data.pop("result", None)
        return data


class JobQueue(abc.ABC):
    """Abstract job queue interface aligned with job-catalog.v1.schema.json."""

    @abc.abstractmethod
    def enqueue(
        self,
        job_type: str,
        owning_service_id: str,
        institution_id: str,
        payload: dict,
        document_id: str | None = None,
        idempotency_scope: str = "document",
        idempotency_key: str | None = None,
        priority: str = "high",
        max_attempts: int = 5,
        concurrency_key: str | None = None,
        delay_seconds: int = 0,
    ) -> Job:
        raise NotImplementedError

    @abc.abstractmethod
    def poll(
        self,
        owning_service_id: str,
        job_types: list[str],
        worker_id: str,
        visibility_timeout_seconds: int = 300,
    ) -> Job | None:
        raise NotImplementedError

    @abc.abstractmethod
    def complete(self, job_id: str, result: dict | None = None) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def fail(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
        retry_delay_seconds: int = 60,
    ) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def get_job(self, job_id: str) -> Job | None:
        raise NotImplementedError


class SqliteJobQueue(JobQueue):
    """SQLite-backed persistent job queue compatible with the baseline runtime schema."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        self._factory = SqliteConnectionFactory(self.db_path)
        self._init_db()

    def _conn(self):
        return self._factory.connect()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_queue (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    owning_service_id TEXT NOT NULL,
                    institution_id TEXT NOT NULL,
                    document_id TEXT,
                    idempotency_scope TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    visible_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    concurrency_key TEXT,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    last_error_code TEXT,
                    last_error_message TEXT,
                    dead_lettered_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lock_version INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (job_type, institution_id, idempotency_key)
                );
                """
            )
            conn.commit()

    def enqueue(
        self,
        job_type: str,
        owning_service_id: str,
        institution_id: str,
        payload: dict,
        document_id: str | None = None,
        idempotency_scope: str = "document",
        idempotency_key: str | None = None,
        priority: str = "high",
        max_attempts: int = 5,
        concurrency_key: str | None = None,
        delay_seconds: int = 0,
    ) -> Job:
        job_id = str(uuid.uuid4())
        now = utc_now_iso()
        key = idempotency_key or str(uuid.uuid4())
        visible_at = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()

        with self._conn() as conn:
            # Check existing idempotent job
            cur = conn.execute(
                """
                SELECT * FROM job_queue
                WHERE job_type = ? AND institution_id = ? AND idempotency_key = ?
                """,
                (job_type, institution_id, key),
            )
            row = cur.fetchone()
            if row and row["status"] in ("pending", "processing", "failed"):
                return self._row_to_job(row)
            if row:
                # A finished job with the same key is archived so the work can run again.
                conn.execute(
                    "UPDATE job_queue SET idempotency_key = ? WHERE job_id = ?",
                    (f"{key}#{row['job_id']}", row["job_id"]),
                )

            conn.execute(
                """
                INSERT INTO job_queue (
                    job_id, job_type, owning_service_id, institution_id,
                    document_id, idempotency_scope, idempotency_key, priority,
                    status, visible_at, attempts, max_attempts, concurrency_key,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    job_type,
                    owning_service_id,
                    institution_id,
                    document_id,
                    idempotency_scope,
                    key,
                    priority,
                    "pending",
                    visible_at,
                    max_attempts,
                    concurrency_key,
                    json.dumps(payload),
                    now,
                    now,
                ),
            )
            conn.commit()

        job = self.get_job(job_id)
        if not job:
            raise RuntimeError("Failed to retrieve enqueued job")
        return job

    def poll(
        self,
        owning_service_id: str,
        job_types: list[str],
        worker_id: str,
        visibility_timeout_seconds: int = 300,
    ) -> Job | None:
        now = utc_now_iso()
        with self._conn() as conn:
            placeholders = ",".join("?" for _ in job_types)
            sql = f"""
                SELECT * FROM job_queue
                WHERE owning_service_id = ?
                  AND job_type IN ({placeholders})
                  AND (
                    (status IN ('pending', 'failed') AND visible_at <= ?)
                    OR (status = 'processing' AND visible_at <= ?)
                  )
                  AND attempts < max_attempts
                ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, visible_at ASC
                LIMIT 1
            """
            params = [owning_service_id, *job_types, now, now]
            cur = conn.execute(sql, params)
            row = cur.fetchone()
            if not row:
                return None

            job_id = row["job_id"]
            new_attempts = row["attempts"] + 1
            # Lease job: update visible_at to future timeout
            next_visible_iso = (
                datetime.now(timezone.utc) + timedelta(seconds=visibility_timeout_seconds)
            ).isoformat()

            conn.execute(
                """
                UPDATE job_queue
                SET status = 'processing',
                    attempts = ?,
                    visible_at = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (new_attempts, next_visible_iso, now, job_id),
            )
            conn.commit()

        return self.get_job(job_id)

    def complete(self, job_id: str, result: dict | None = None) -> bool:
        now = utc_now_iso()
        with self._conn() as conn:
            res = conn.execute(
                """
                UPDATE job_queue
                SET status = 'completed',
                    result_json = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (json.dumps(result or {}), now, job_id),
            )
            conn.commit()
            return res.rowcount > 0

    def fail(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
        retry_delay_seconds: int = 60,
    ) -> bool:
        now = utc_now_iso()
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT attempts, max_attempts FROM job_queue WHERE job_id = ?", (job_id,)
            )
            row = cur.fetchone()
            if not row:
                return False

            is_dead_letter = row["attempts"] >= row["max_attempts"]
            status = "dead_letter" if is_dead_letter else "failed"
            dead_lettered_at = now if is_dead_letter else None

            next_visible_iso = (
                datetime.now(timezone.utc) + timedelta(seconds=retry_delay_seconds)
            ).isoformat()

            conn.execute(
                """
                UPDATE job_queue
                SET status = ?,
                    last_error_code = ?,
                    last_error_message = ?,
                    visible_at = ?,
                    dead_lettered_at = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (
                    status,
                    error_code,
                    error_message,
                    next_visible_iso,
                    dead_lettered_at,
                    now,
                    job_id,
                ),
            )
            conn.commit()
            return True

    def get_job(self, job_id: str) -> Job | None:
        with self._conn() as conn:
            cur = conn.execute("SELECT * FROM job_queue WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_job(row)

    def list_jobs(self, document_id: str | None = None, limit: int = 50) -> list[Job]:
        query = "SELECT * FROM job_queue"
        params: list = []
        if document_id:
            query += " WHERE document_id = ?"
            params.append(document_id)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            return [self._row_to_job(row) for row in conn.execute(query, params).fetchall()]

    def count_by_status(self, institution_id: str | None = None) -> dict[str, int]:
        query = "SELECT status, COUNT(*) AS total FROM job_queue"
        params = []
        if institution_id is not None:
            query += " WHERE institution_id = ?"
            params.append(institution_id)
        with self._conn() as conn:
            rows = conn.execute(query + " GROUP BY status", params).fetchall()
            return {row["status"]: row["total"] for row in rows}

    def has_active_jobs(self, document_id: str | None = None) -> bool:
        query = "SELECT 1 FROM job_queue WHERE status IN ('pending', 'processing', 'failed')"
        params: list = []
        if document_id:
            query += " AND document_id = ?"
            params.append(document_id)
        with self._conn() as conn:
            return conn.execute(query + " LIMIT 1", params).fetchone() is not None

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        result = json.loads(row["result_json"]) if row["result_json"] else None
        return Job(
            job_id=row["job_id"],
            job_type=row["job_type"],
            owning_service_id=row["owning_service_id"],
            institution_id=row["institution_id"],
            document_id=row["document_id"],
            idempotency_scope=row["idempotency_scope"],
            idempotency_key=row["idempotency_key"],
            priority=row["priority"],
            status=row["status"],
            visible_at=row["visible_at"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            concurrency_key=row["concurrency_key"],
            payload=payload,
            result=result,
            last_error_code=row["last_error_code"],
            last_error_message=row["last_error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
