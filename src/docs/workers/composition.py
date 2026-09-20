"""Dependency-injected composition for pipeline worker jobs.

This module translates an immutable queue payload into the small, typed call
surface required by a synchronous pipeline runtime.  It deliberately owns no
pipeline construction, persistence implementation, or worker lifecycle.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from docs.domain.contracts import Job
from docs.domain.ports.x20 import JobQueue, LeaseStore, PassportStore, RunStore
from docs.workers.service import WorkerResult, WorkerService


class PipelineRuntimePort(Protocol):
    """The synchronous pipeline boundary used by a worker job."""

    def run(
        self,
        run_id: str,
        *,
        inputs: Sequence[Path] = (),
        outputs: Sequence[Path] = (),
        excluded_stages: set[str] | frozenset[str] = frozenset(),
        external_artifacts: Sequence[str] | None = None,
    ) -> Any:
        ...


class PipelineRuntimeFactory(Protocol):
    """Create a runtime for a named pipeline without coupling to its setup."""

    def __call__(self, pipeline_id: str) -> PipelineRuntimePort:
        ...


@dataclass(frozen=True)
class PipelineJobConfiguration:
    """Validated pipeline execution fields transported in a :class:`Job`."""

    pipeline_id: str
    run_id: str
    inputs: tuple[Path, ...] = ()
    outputs: tuple[Path, ...] = ()
    excluded_stages: frozenset[str] = frozenset()
    external_artifacts: tuple[str, ...] | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], workspace_root: Path) -> PipelineJobConfiguration:
        """Validate a queue payload and resolve its file paths below ``workspace_root``."""
        if not isinstance(payload, Mapping):
            raise TypeError("job payload must be a mapping")
        return cls(
            pipeline_id=_required_text(payload, "pipeline_id"),
            run_id=_required_text(payload, "run_id"),
            inputs=_paths(payload, "inputs", workspace_root),
            outputs=_paths(payload, "outputs", workspace_root),
            excluded_stages=frozenset(_strings(payload, "excluded_stages")),
            external_artifacts=_optional_strings(payload, "external_artifacts"),
        )


@dataclass(frozen=True)
class WorkerServiceConfiguration:
    """Worker lifecycle dependencies and options supplied by the composition root."""

    queue: JobQueue
    leases: LeaseStore
    run_store: RunStore | None = None
    passport_store: PassportStore | None = None
    finalizer: Callable[[WorkerResult], Any] | None = None
    scratch_parent: str | Path | None = None
    worker_id: str | None = None
    lease_ttl_seconds: int = 60
    max_retries: int = 0


class WorkerComposition:
    """Build a :class:`WorkerService` whose handler runs typed pipeline jobs."""

    def __init__(
        self,
        runtime_factory: PipelineRuntimeFactory,
        workspace_root: str | Path,
        queue: JobQueue,
        leases: LeaseStore,
        *,
        run_store: RunStore | None = None,
        passport_store: PassportStore | None = None,
        finalizer: Callable[[WorkerResult], Any] | None = None,
        scratch_parent: str | Path | None = None,
        worker_id: str | None = None,
        lease_ttl_seconds: int = 60,
        max_retries: int = 0,
    ) -> None:
        self._runtime_factory = runtime_factory
        self._workspace_root = Path(workspace_root).resolve()
        self._service = WorkerServiceConfiguration(
            queue=queue,
            leases=leases,
            run_store=run_store,
            passport_store=passport_store,
            finalizer=finalizer,
            scratch_parent=scratch_parent,
            worker_id=worker_id,
            lease_ttl_seconds=lease_ttl_seconds,
            max_retries=max_retries,
        )

    def handle(self, job: Job, _scratch: Path | None = None) -> Any:
        """Synchronously run the pipeline described by ``job.payload``."""
        configuration = PipelineJobConfiguration.from_payload(job.payload, self._workspace_root)
        runtime = self._runtime_factory(configuration.pipeline_id)
        result = runtime.run(
            configuration.run_id,
            inputs=configuration.inputs,
            outputs=configuration.outputs,
            excluded_stages=configuration.excluded_stages,
            external_artifacts=configuration.external_artifacts,
        )
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise TypeError("pipeline runtime handler must be synchronous")
        return result

    def create_service(self) -> WorkerService:
        """Return a worker service wired to this composition's synchronous handler."""
        options = self._service
        return WorkerService(
            options.queue,
            options.leases,
            self.handle,
            run_store=options.run_store,
            passport_store=options.passport_store,
            finalizer=options.finalizer,
            scratch_parent=options.scratch_parent,
            worker_id=options.worker_id,
            lease_ttl_seconds=options.lease_ttl_seconds,
            max_retries=options.max_retries,
        )

    build = create_service


def _required_text(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if type(value) is not str or not value:
        raise TypeError(f"{field_name} must be a non-empty string")
    return value


def _strings(payload: Mapping[str, Any], field_name: str) -> tuple[str, ...]:
    value = payload.get(field_name, [])
    if type(value) is not list:
        raise TypeError(f"{field_name} must be a list of non-empty strings")
    if any(type(item) is not str or not item for item in value):
        raise TypeError(f"{field_name} must be a list of non-empty strings")
    return tuple(value)


def _optional_strings(payload: Mapping[str, Any], field_name: str) -> tuple[str, ...] | None:
    if field_name not in payload or payload[field_name] is None:
        return None
    return _strings(payload, field_name)


def _paths(payload: Mapping[str, Any], field_name: str, workspace_root: Path) -> tuple[Path, ...]:
    return tuple(_workspace_path(value, field_name, workspace_root) for value in _strings(payload, field_name))


def _workspace_path(value: str, field_name: str, workspace_root: Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"{field_name} paths must be relative to workspace_root")
    resolved = (workspace_root / candidate).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"{field_name} path escapes workspace_root") from exc
    return resolved
