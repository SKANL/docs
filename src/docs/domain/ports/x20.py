from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from docs.domain.contracts import SCHEMA, Artifact, Blob, Graph, Job, Passport, Run
from docs.domain.ports.document_renderer_port import DocumentRendererPort
from docs.domain.ports.document_repository import DocumentRepository
from docs.domain.ports.render_verification_port import RenderVerificationPort

X20_PORT_CONTRACT = SCHEMA


class DocumentStore(DocumentRepository, Protocol):
    """Version 1 public document-persistence boundary."""


class Renderer(DocumentRendererPort, Protocol):
    """Version 1 public document-rendering boundary."""


class Verifier(RenderVerificationPort, Protocol):
    """Version 1 public rendered-artifact verification boundary."""


class PluginExecutor(Protocol):
    """Version 1 public boundary for isolated plugin execution."""

    def run(
        self,
        manifest: Any,
        payload: Any,
        publication_dir: Path | None = None,
        *,
        trusted_token: str | None = None,
    ) -> Any: ...


class RunStore(Protocol):
    def put(self, run: Run) -> None: ...
    def get(self, run_id: str) -> Run | None: ...


class PassportStore(Protocol):
    def put(self, passport: Passport) -> None: ...
    def get(self, run_id: str) -> Passport | None: ...


class ArtifactStore(Protocol):
    def put(self, artifact: Artifact) -> None: ...
    def get(self, artifact_id: str) -> Artifact | None: ...
    def list_for_run(self, run_id: str) -> list[Artifact]: ...


class BlobStore(Protocol):
    def put(self, blob: Blob, content: bytes) -> None: ...
    def put_conditional(self, blob: Blob, content: bytes, *, expected_digest: str | None) -> bool: ...
    def compare_and_swap(self, key: str, expected_digest: str | None, blob: Blob, content: bytes) -> bool: ...
    def get(self, key: str) -> tuple[Blob, bytes] | None: ...


class GraphStore(Protocol):
    def put(self, graph: Graph) -> None: ...
    def get(self) -> Graph: ...


class JobQueue(Protocol):
    def enqueue(self, job_id: str, payload: dict[str, object]) -> None: ...
    def claim(self, worker_id: str) -> Job | None: ...
    def ack(self, job_id: str, worker_id: str) -> bool: ...


class CancellableJobQueue(JobQueue, Protocol):
    """Optional durable cancellation surface shared by worker and API paths."""

    def cancel(self, run_id: str) -> bool: ...
    def is_cancelled(self, run_id: str) -> bool: ...


class LeaseStore(Protocol):
    def acquire(self, resource: str, owner: str, ttl_seconds: int) -> bool: ...
    def renew(self, resource: str, owner: str, ttl_seconds: int) -> bool: ...
    def release(self, resource: str, owner: str) -> bool: ...
