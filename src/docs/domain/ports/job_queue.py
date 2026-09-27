from __future__ import annotations

from typing import Protocol

from docs.domain.runtime_records import Job


class JobQueue(Protocol):
    def enqueue(self, job_id: str, payload: dict[str, object]) -> None: ...
    def claim(self, worker_id: str) -> Job | None: ...
    def ack(self, job_id: str, worker_id: str) -> bool: ...


class CancellableJobQueue(JobQueue, Protocol):
    """Optional durable cancellation surface shared by worker and API paths."""

    def cancel(self, run_id: str) -> bool: ...
    def is_cancelled(self, run_id: str) -> bool: ...
