from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from xtract.storage.queue import Job, JobQueue

logger = logging.getLogger("queue-worker")


@dataclass
class JobHandler:
    """Binds a queue owner and job types to the function that processes them."""

    owning_service_id: str
    job_types: list[str]
    process: Callable[[Job], dict]
    error_code: str = "JOB_PROCESSING_FAILED"


class QueueWorker:
    """Polls the job queue and dispatches jobs to registered handlers."""

    def __init__(
        self,
        queue: JobQueue,
        handlers: list[JobHandler],
        on_dead_letter: Callable[[Job, str], None] | None = None,
        retry_delay_seconds: int = 5,
        worker_id: str | None = None,
    ) -> None:
        self.queue = queue
        self.handlers = handlers
        self.on_dead_letter = on_dead_letter
        self.retry_delay_seconds = retry_delay_seconds
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()

    def run_once(self) -> bool:
        """Process at most one job per handler. Returns True if any job ran."""
        did_work = False
        for handler in self.handlers:
            job = self.queue.poll(
                owning_service_id=handler.owning_service_id,
                job_types=handler.job_types,
                worker_id=self.worker_id,
            )
            if not job:
                continue
            did_work = True
            try:
                result = handler.process(job)
                self.queue.complete(job.job_id, result=result)
            except Exception as exc:
                logger.exception("Job %s (%s) failed", job.job_id, job.job_type)
                self.queue.fail(
                    job_id=job.job_id,
                    error_code=handler.error_code,
                    error_message=str(exc)[:1000],
                    retry_delay_seconds=self.retry_delay_seconds,
                )
                if job.attempts >= job.max_attempts and self.on_dead_letter:
                    try:
                        self.on_dead_letter(job, str(exc))
                    except Exception:
                        logger.exception("Dead-letter handler failed for job %s", job.job_id)
        return did_work

    def drain(self, max_jobs: int = 1000) -> int:
        """Run jobs until the queue has no ready work. Returns the number of loop passes."""
        passes = 0
        while passes < max_jobs and self.run_once():
            passes += 1
        return passes

    def run_forever(self, poll_interval_seconds: float = 1.0) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            if not self.run_once():
                self._stop.wait(poll_interval_seconds)

    def stop(self) -> None:
        self._stop.set()
