from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from uuid import uuid4

from .utils import format_duration


@dataclass
class TranscriptionJob:
    id: str
    source_filename: str
    output_format: str
    total_seconds: float | None
    status: str = "queued"
    stage: str = "ready"
    message: str = "Ready"
    processed_seconds: float = 0.0
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


_jobs: dict[str, TranscriptionJob] = {}
_lock = Lock()


def create_job(source_filename: str, output_format: str, total_seconds: float | None) -> TranscriptionJob:
    job = TranscriptionJob(
        id=uuid4().hex,
        source_filename=source_filename,
        output_format=output_format,
        total_seconds=total_seconds,
        status="running",
        stage="preparing",
        message="Preparing file",
    )
    with _lock:
        _jobs[job.id] = job
    return job


def get_job(job_id: str) -> TranscriptionJob | None:
    with _lock:
        return _jobs.get(job_id)


def update_job(job_id: str, **changes: Any) -> None:
    with _lock:
        job = _jobs[job_id]
        for key, value in changes.items():
            setattr(job, key, value)


def complete_job(job_id: str, result: dict[str, Any]) -> None:
    with _lock:
        job = _jobs[job_id]
        job.status = "complete"
        job.stage = "complete"
        job.message = "Complete"
        job.processed_seconds = job.total_seconds or job.processed_seconds
        job.finished_at = time.monotonic()
        job.result = result


def fail_job(job_id: str, message: str) -> None:
    with _lock:
        job = _jobs[job_id]
        job.status = "error"
        job.stage = "error"
        job.message = message
        job.error = message
        job.finished_at = time.monotonic()


def job_progress(job: TranscriptionJob) -> dict[str, Any]:
    now = job.finished_at or time.monotonic()
    elapsed = max(0.0, now - job.started_at)
    total = job.total_seconds or 0.0
    processed = min(max(job.processed_seconds, 0.0), total) if total else max(job.processed_seconds, 0.0)
    progress = (processed / total * 100) if total > 0 else 0.0
    if job.status == "complete":
        progress = 100.0

    remaining = None
    if job.status == "running" and progress > 0:
        estimated_total = elapsed / (progress / 100)
        remaining = max(0.0, estimated_total - elapsed)

    return {
        "job_id": job.id,
        "stage": job.stage,
        "status": job.status,
        "progress": round(progress, 1),
        "elapsed_seconds": round(elapsed),
        "estimated_remaining_seconds": round(remaining) if remaining is not None else None,
        "processed_seconds": round(processed, 3),
        "total_seconds": round(total, 3) if total else None,
        "processed": _processed_label(processed, total),
        "message": job.message,
        "error": job.error,
    }


def _processed_label(processed: float, total: float) -> str:
    if total <= 0:
        return f"{format_duration(processed) or '00:00:00'} / --:--"
    return f"{format_duration(processed)} / {format_duration(total)}"
