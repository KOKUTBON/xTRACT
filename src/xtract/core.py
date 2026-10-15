"""Platform composition: wires storage, queue, services, and background worker."""

from __future__ import annotations

import json
import logging
import threading

from xtract.assistant.assistant import DocumentAssistant
from xtract.auth.service import AuthService
from xtract.config import PlatformConfig
from xtract.extraction.extractor import MetadataExtractor
from xtract.extraction.worker import ExtractionWorker
from xtract.intake.config import IntakeConfig
from xtract.intake.service import IntakeService
from xtract.integration.dispatcher import ProtocolDispatcher
from xtract.integration.worker import IntegrationWorker
from xtract.ocr.engines import default_engines
from xtract.ocr.orchestrator import OcrOrchestrator
from xtract.review.commands import BackofficeCommands
from xtract.review.export import DatasetExporter
from xtract.review.projections import BackofficeProjections
from xtract.storage.database import RuntimeDatabase
from xtract.storage.queue import Job, SqliteJobQueue
from xtract.storage.storage import LocalStorageClient
from xtract.storage.worker import JobHandler, QueueWorker

logger = logging.getLogger("xtract")


class Platform:
    """Wires storage, queue, services, and the background worker together."""

    def __init__(
        self, config: PlatformConfig | None = None, ocr_engines=None, connectors=None, sleep=None
    ) -> None:
        self.config = cfg = config or PlatformConfig()
        self.auth = AuthService(cfg)
        self.db = RuntimeDatabase(cfg.database_path)
        self.queue = SqliteJobQueue(cfg.database_path)
        self.storage = LocalStorageClient(cfg.storage_root)

        self.field_taxonomy = json.loads(
            cfg.config_file("field-taxonomy.v1.json").read_text("utf-8")
        )
        self.extractor = MetadataExtractor(
            alias_dictionary=cfg.config_file("alias-dictionary.v1.json"),
            field_taxonomy=self.field_taxonomy,
            extraction_policy=cfg.config_file("extraction-policy.v1.json"),
        )
        self.intake = IntakeService(
            IntakeConfig(
                max_file_size_bytes=cfg.max_upload_bytes, reject_duplicates=cfg.reject_duplicates
            ),
            self.db,
            self.storage,
            self.queue,
        )
        self.ocr = OcrOrchestrator(
            self.db,
            self.storage,
            self.queue,
            routing_policy=cfg.config_file("ocr-routing-policy.v1.json"),
            engines=ocr_engines or default_engines(languages=cfg.tesseract_lang),
        )
        dispatcher_kwargs = {"sleep": sleep} if sleep else {}
        self.dispatcher = ProtocolDispatcher(
            cfg.config_file("connector-catalog.v1.json"),
            cfg.config_file("integration-policy.v1.json"),
            database=self.db,
            connectors=connectors,
            **dispatcher_kwargs,
        )
        extraction = ExtractionWorker(self.queue, self.db, self.storage, self.extractor)
        integration = IntegrationWorker(self.queue, self.db, self.storage, self.dispatcher)

        self.projections = BackofficeProjections(
            self.db, self.queue, cfg.exception_taxonomy_path, self.field_taxonomy
        )
        self.commands = BackofficeCommands(self.db, self.queue, self.extractor)
        self.assistant = DocumentAssistant(self.db)
        self.exporter = DatasetExporter(self.db)

        self.worker = QueueWorker(
            self.queue,
            [
                JobHandler(
                    "ocr-orchestrator",
                    ["ocr.process_document"],
                    self.ocr.process_job,
                    "OCR_PROCESSING_FAILED",
                ),
                JobHandler(
                    "extraction-engine",
                    ["extraction.extract_metadata"],
                    extraction.process_job,
                    "EXTRACTION_PROCESSING_FAILED",
                ),
                JobHandler(
                    "integration-hub",
                    ["integration.dispatch_protocol"],
                    integration.process_job,
                    "INTEGRATION_PROCESSING_FAILED",
                ),
            ],
            on_dead_letter=self._on_dead_letter,
        )
        self._thread: threading.Thread | None = None

    def _on_dead_letter(self, job: Job, error: str) -> None:
        document_id = job.document_id or job.payload.get("document_id")
        doc = self.db.get_document(document_id) if document_id else None
        if not doc:
            return
        code = {
            "ocr.process_document": "ocr_engine_failure",
            "integration.dispatch_protocol": "protocol_system_unavailable",
        }.get(job.job_type, "required_metadata_missing")
        self.db.record_exception(
            document_id,
            code,
            "high",
            source_service=job.owning_service_id,
            payload={"message": f"{job.job_type} failed after {job.attempts} attempts: {error}"},
        )
        if job.job_type != "integration.dispatch_protocol":
            self.db.update_document_stage(document_id, "failed", {"failure_reason": error})
        self.db.record_audit_event(
            "document.failed",
            doc["institution_id"],
            document_id,
            "service",
            job.owning_service_id,
            "JOB_DEAD_LETTERED",
            {"job_type": job.job_type, "error": error[:300]},
        )

    @property
    def institution_profile(self) -> dict:
        return self.config.get_institution_profile()

    def document_families(self) -> list[dict]:
        return [
            {
                "family_code": t["family_code"],
                "type_code": t["type_code"],
                "display_name": t["display_name"],
                "fields": [
                    {k: f.get(k) for k in ("field_code", "label", "value_type", "required")}
                    for f in t.get("fields", [])
                ],
            }
            for t in self.field_taxonomy.get("document_types", [])
        ]

    def process_pending(self) -> int:
        """Run queued jobs synchronously until none are ready (used by the CLI and tests)."""
        return self.worker.drain()

    def start_worker(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self.worker.run_forever,
            kwargs={"poll_interval_seconds": self.config.worker_poll_seconds},
            name="xtract-worker",
            daemon=True,
        )
        self._thread.start()

    def stop_worker(self) -> None:
        self.worker.stop()
        if self._thread:
            self._thread.join(timeout=5)
