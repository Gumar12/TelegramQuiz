"""In-process jobs and live progress events for QuizBot Studio."""
from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class JobCancelled(RuntimeError):
    """Raised inside a job when the user requests cancellation."""


def _now_time() -> str:
    return time.strftime("%H:%M:%S")


@dataclass
class JobState:
    id: str
    type: str
    status: str = "running"
    progress: int = 0
    stage: str = ""
    current_group: str = ""
    current_step: str = "Starting"
    eta: int = 0
    logs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str = ""
    cancel_requested: bool = False


class JobManager:
    def __init__(self, max_workers: int = 2):
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def create_job(self, job_type: str) -> JobState:
        job = JobState(id=uuid4().hex, type=job_type)
        with self._lock:
            self._jobs[job.id] = job
        self.emit(job.id, stage=job_type, progress=0, message="Job created")
        return job

    def get(self, job_id: str) -> JobState:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._jobs[job_id]

    def snapshot(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.get(job_id)
            return {
                "id": job.id,
                "type": job.type,
                "status": job.status,
                "progress": job.progress,
                "stage": job.stage,
                "current_group": job.current_group,
                "current_step": job.current_step,
                "eta": job.eta,
                "logs": list(job.logs),
                "warnings": list(job.warnings),
                "result": job.result,
                "error": job.error,
                "cancel_requested": job.cancel_requested,
            }

    def events_since(self, job_id: str, index: int) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.get(job_id).events[index:])

    def emit(
        self,
        job_id: str,
        *,
        stage: str | None = None,
        progress: int | None = None,
        message: str,
        group: str | None = None,
        log_type: str = "info",
        eta: int | None = None,
        warning: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            job = self.get(job_id)
            if stage is not None:
                job.stage = stage
            if progress is not None:
                job.progress = max(0, min(100, int(progress)))
            if group is not None:
                job.current_group = group
            if eta is not None:
                job.eta = max(0, int(eta))
            job.current_step = message
            if warning:
                job.warnings.append(warning)
            if result is not None:
                job.result = result

            log = {"time": _now_time(), "message": message, "type": log_type}
            job.logs.append(log)
            event = {
                "index": len(job.events),
                "job_id": job.id,
                "status": job.status,
                "type": job.type,
                "stage": job.stage,
                "progress": job.progress,
                "current_group": job.current_group,
                "current_step": job.current_step,
                "eta": job.eta,
                "message": message,
                "log": log,
                "warnings": list(job.warnings),
                "result": job.result,
                "error": job.error,
            }
            job.events.append(event)
            return event

    def complete(self, job_id: str, result: dict[str, Any] | None = None) -> None:
        with self._lock:
            job = self.get(job_id)
            job.status = "completed"
            job.progress = 100
            if result is not None:
                job.result = result
        self.emit(job_id, progress=100, message="Job completed", log_type="success", result=result)

    def fail(self, job_id: str, exc: BaseException) -> None:
        with self._lock:
            job = self.get(job_id)
            job.status = "failed"
            job.progress = 100
            job.error = str(exc)
            job.result = {"traceback": traceback.format_exc()}
        self.emit(job_id, progress=100, message=str(exc), log_type="error")

    def cancel(self, job_id: str) -> None:
        with self._lock:
            job = self.get(job_id)
            job.cancel_requested = True
            if job.status in TERMINAL_STATUSES:
                return
        self.emit(job_id, message="Cancel requested", log_type="warn")

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            return self.get(job_id).cancel_requested

    def raise_if_cancelled(self, job_id: str) -> None:
        if self.is_cancel_requested(job_id):
            raise JobCancelled("Job cancelled")

    def run_in_thread(
        self,
        job_type: str,
        target: Callable[[str, "JobManager"], dict[str, Any] | None],
    ) -> JobState:
        job = self.create_job(job_type)

        def runner() -> None:
            try:
                result = target(job.id, self)
                with self._lock:
                    current = self.get(job.id)
                    if current.cancel_requested and current.status not in TERMINAL_STATUSES:
                        current.status = "cancelled"
                if self.snapshot(job.id)["status"] == "cancelled":
                    self.emit(job.id, progress=100, message="Job cancelled", log_type="warn")
                    return
                self.complete(job.id, result or {})
            except JobCancelled as exc:
                with self._lock:
                    current = self.get(job.id)
                    current.status = "cancelled"
                    current.progress = 100
                    current.error = str(exc)
                self.emit(job.id, progress=100, message=str(exc), log_type="warn")
            except BaseException as exc:  # noqa: BLE001 - job boundary must capture all failures
                self.fail(job.id, exc)

        self._executor.submit(runner)
        return job
