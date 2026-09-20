from __future__ import annotations

from collections import deque
from time import monotonic

from docs.domain.contracts import Artifact, Blob, Graph, Job, Passport, Run


class InMemoryRunStore:
    def __init__(self) -> None:
        self._items: dict[str, Run] = {}

    def put(self, run: Run) -> None:
        self._items[run.id] = run

    def get(self, run_id: str) -> Run | None:
        return self._items.get(run_id)


class InMemoryPassportStore:
    def __init__(self) -> None:
        self._items: dict[str, Passport] = {}

    def put(self, passport: Passport) -> None:
        self._items[passport.run_id] = passport

    def get(self, run_id: str) -> Passport | None:
        return self._items.get(run_id)


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._items: dict[str, Artifact] = {}

    def put(self, artifact: Artifact) -> None:
        self._items[artifact.id] = artifact

    def get(self, artifact_id: str) -> Artifact | None:
        return self._items.get(artifact_id)

    def list_for_run(self, run_id: str) -> list[Artifact]:
        return [item for item in self._items.values() if item.run_id == run_id]


class InMemoryBlobStore:
    def __init__(self) -> None:
        self._items: dict[str, tuple[Blob, bytes]] = {}

    def put(self, blob: Blob, content: bytes) -> None:
        self._items[blob.key] = (blob, bytes(content))

    def get(self, key: str) -> tuple[Blob, bytes] | None:
        return self._items.get(key)


class InMemoryGraphStore:
    def __init__(self) -> None:
        self._graph = Graph()

    def put(self, graph: Graph) -> None:
        self._graph = graph

    def get(self) -> Graph:
        return self._graph


class InMemoryJobQueue:
    def __init__(self) -> None:
        self._pending: deque[Job] = deque()
        self._claimed: dict[str, str] = {}
        self._job_ids: set[str] = set()
        self._cancelled: set[str] = set()

    def enqueue(self, job_id: str, payload: dict[str, object]) -> None:
        if job_id in self._job_ids:
            return
        self._pending.append(Job(job_id, dict(payload)))
        self._job_ids.add(job_id)

    def claim(self, worker_id: str) -> Job | None:
        if not self._pending:
            return None
        job = self._pending.popleft()
        self._claimed[job.id] = worker_id
        return job

    def ack(self, job_id: str, worker_id: str) -> bool:
        if self._claimed.get(job_id) != worker_id:
            return False
        del self._claimed[job_id]
        self._job_ids.remove(job_id)
        return True

    def cancel(self, run_id: str) -> bool:
        before = len(self._cancelled)
        self._cancelled.add(run_id)
        return len(self._cancelled) != before

    def is_cancelled(self, run_id: str) -> bool:
        return run_id in self._cancelled


class InMemoryLeaseStore:
    def __init__(self) -> None:
        self._leases: dict[str, tuple[str, float]] = {}

    def _discard_expired(self, resource: str) -> None:
        lease = self._leases.get(resource)
        if lease is not None and lease[1] <= monotonic():
            del self._leases[resource]

    def acquire(self, resource: str, owner: str, ttl_seconds: int) -> bool:
        self._discard_expired(resource)
        if resource in self._leases:
            return False
        self._leases[resource] = (owner, monotonic() + ttl_seconds)
        return True

    def renew(self, resource: str, owner: str, ttl_seconds: int) -> bool:
        self._discard_expired(resource)
        if self._leases.get(resource, (None, 0))[0] != owner:
            return False
        self._leases[resource] = (owner, monotonic() + ttl_seconds)
        return True

    def release(self, resource: str, owner: str) -> bool:
        self._discard_expired(resource)
        if self._leases.get(resource, (None, 0))[0] != owner:
            return False
        del self._leases[resource]
        return True
