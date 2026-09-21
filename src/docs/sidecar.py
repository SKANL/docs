"""Desktop sidecar entrypoint for the local X20 API."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
from datetime import UTC, datetime
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .api.application import X20Application
from .plugins import PluginRegistry
from .application.workspaces import WorkspaceRegistry, WorkspaceRegistryError
from .api.http import Response, Router
from .api.server import GracefulHTTPServer, TransportConfig, create_server, serve
from .infrastructure.persistence.x20 import (
    SqliteArtifactStore,
    SqliteGraphStore,
    SqliteFindingStore,
    SqliteJobQueue,
    SqliteLeaseStore,
    SqlitePassportStore,
    SqlitePublicationStore,
    SqliteRunStore,
)
from .workers.composition import WorkerComposition
from .workers.runner import WorkerRunner
from .domain.contracts import Artifact, Passport
import hashlib

_LOG = logging.getLogger("docs.sidecar")


class _FilesystemDocumentStore:
    """Read real document manifests for the local API; never synthesizes rows."""

    def __init__(self, workspace: Path, registry: WorkspaceRegistry | None = None) -> None:
        self.root = workspace.resolve() / "documents"
        self.registry = registry

    def _documents_root(self) -> Path:
        if self.registry is not None:
            active = self.registry.active()
            if active is not None:
                return Path(str(active["root"])).resolve() / "documents"
        return self.root

    def list_for_workspace(self, workspace_root: str | Path) -> list[dict[str, Any]]:
        return self._list_from_root(Path(workspace_root).expanduser().resolve() / "documents")

    @staticmethod
    def _list_from_root(root: Path) -> list[dict[str, Any]]:
        if not root.is_dir():
            return []
        items: list[dict[str, Any]] = []
        for path in sorted(root.glob("*/document.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(value, dict):
                value.setdefault("id", path.parent.name)
                items.append(value)
        return items

    def list(self) -> list[dict[str, Any]]:
        return self._list_from_root(self._documents_root())

    def get(self, document_id: str) -> dict[str, Any] | None:
        path = self._documents_root() / document_id / "document.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(value, dict):
            return None
        value.setdefault("id", document_id)
        return value


class _WorkspaceRunStore:
    """Route durable run records to the SQLite database of their workspace."""

    def __init__(self, registry: WorkspaceRegistry, fallback_root: Path | None = None) -> None:
        self.registry = registry
        self.fallback_root = fallback_root.resolve() if fallback_root is not None else None
        self._stores: dict[str, SqliteRunStore] = {}

    @property
    def path(self) -> Path:
        if self.fallback_root is None:
            raise AttributeError("workspace run store has no fallback path")
        return self.fallback_root / ".docs" / "x20.sqlite3"

    def _store(self, root: str | Path) -> SqliteRunStore:
        resolved = Path(root).expanduser().resolve()
        key = str(resolved)
        if key not in self._stores:
            self._stores[key] = SqliteRunStore(resolved / ".docs" / "x20.sqlite3")
        return self._stores[key]

    def _all(self) -> list[SqliteRunStore]:
        roots = [Path(item["root"]).resolve() for item in self.registry.list()]
        if self.fallback_root is not None and self.fallback_root not in roots:
            roots.append(self.fallback_root)
        return [self._store(root) for root in roots]

    def put(self, run: Any) -> None:
        workspace_id = run.payload.get("workspace_id") if isinstance(run.payload, Mapping) else None
        if isinstance(workspace_id, str) and workspace_id:
            self._store(self.registry.get(workspace_id)["root"]).put(run)
        elif self.fallback_root is not None:
            self._store(self.fallback_root).put(run)
        else:
            raise ValueError("workspace_id is required for durable runs")

    def get(self, run_id: str) -> Any:
        for store in self._all():
            item = store.get(run_id)
            if item is not None:
                return item
        return None

    def list(self) -> list[Any]:
        items = [item for store in self._all() for item in store.list()]
        return sorted(items, key=lambda item: item.id)


class _WorkspaceJobQueue:
    """Queue facade that claims work from every registered workspace."""

    def __init__(self, registry: WorkspaceRegistry, fallback_root: Path | None = None) -> None:
        self.registry = registry
        self.fallback_root = fallback_root.resolve() if fallback_root is not None else None
        self._queues: dict[str, SqliteJobQueue] = {}

    @property
    def path(self) -> Path:
        if self.fallback_root is None:
            raise AttributeError("workspace queue has no fallback path")
        return self.fallback_root / ".docs" / "x20.sqlite3"

    def _queue(self, root: str | Path) -> SqliteJobQueue:
        resolved = Path(root).expanduser().resolve()
        key = str(resolved)
        if key not in self._queues:
            self._queues[key] = SqliteJobQueue(resolved / ".docs" / "x20.sqlite3")
        return self._queues[key]

    def enqueue(self, job_id: str, payload: dict[str, object]) -> None:
        workspace_id = payload.get("workspace_id")
        if isinstance(workspace_id, str) and workspace_id:
            self._queue(self.registry.get(workspace_id)["root"]).enqueue(job_id, payload)
        elif self.fallback_root is not None:
            self._queue(self.fallback_root).enqueue(job_id, payload)
        else:
            raise ValueError("workspace_id is required for queued runs")

    def claim(self, worker_id: str) -> Any:
        roots = [item["root"] for item in self.registry.list()]
        if self.fallback_root is not None and str(self.fallback_root) not in {str(Path(root).resolve()) for root in roots}:
            roots.append(self.fallback_root)
        for root in roots:
            job = self._queue(root).claim(worker_id)
            if job is not None:
                return job
        return None

    def ack(self, job_id: str, worker_id: str) -> bool:
        return any(queue.ack(job_id, worker_id) for queue in self._queues.values())

    def cancel(self, run_id: str) -> bool:
        return any(queue.cancel(run_id) for queue in self._queues.values())

    def is_cancelled(self, run_id: str) -> bool:
        return any(queue.is_cancelled(run_id) for queue in self._queues.values())


class _WorkspaceEvidenceStores:
    """Route passport, artifact, and finding projections by their run owner."""

    def __init__(self, registry: WorkspaceRegistry, run_store: _WorkspaceRunStore, fallback_root: Path) -> None:
        self.registry = registry
        self.run_store = run_store
        self.fallback_root = fallback_root.resolve()
        self._stores: dict[str, tuple[SqlitePassportStore, SqliteArtifactStore, SqliteFindingStore, SqlitePublicationStore]] = {}

    def _stores_for_root(self, root: str | Path) -> tuple[SqlitePassportStore, SqliteArtifactStore, SqliteFindingStore, SqlitePublicationStore]:
        resolved = Path(root).expanduser().resolve()
        key = str(resolved)
        if key not in self._stores:
            state = resolved / ".docs" / "x20.sqlite3"
            self._stores[key] = (SqlitePassportStore(state), SqliteArtifactStore(state), SqliteFindingStore(state), SqlitePublicationStore(state))
        return self._stores[key]

    def _root_for_run(self, run_id: str) -> Path:
        run = self.run_store.get(run_id)
        if run is not None and isinstance(run.payload, Mapping):
            workspace_id = run.payload.get("workspace_id")
            if isinstance(workspace_id, str) and workspace_id:
                try:
                    return Path(str(self.registry.get(workspace_id)["root"])).resolve()
                except Exception:
                    pass
        return self.fallback_root

    def passport(self) -> "_WorkspacePassportStore":
        return _WorkspacePassportStore(self)

    def artifact(self) -> "_WorkspaceArtifactStore":
        return _WorkspaceArtifactStore(self)

    def finding(self) -> "_WorkspaceFindingStore":
        return _WorkspaceFindingStore(self)

    def publication(self) -> "_WorkspacePublicationStore":
        return _WorkspacePublicationStore(self)


class _WorkspacePassportStore:
    def __init__(self, parent: _WorkspaceEvidenceStores) -> None: self.parent = parent
    @property
    def path(self) -> Path: return self.parent.fallback_root / ".docs" / "x20.sqlite3"
    def put(self, value: Passport) -> None: self.parent._stores_for_root(self.parent._root_for_run(value.run_id))[0].put(value)
    def get(self, run_id: str) -> Any: return self.parent._stores_for_root(self.parent._root_for_run(run_id))[0].get(run_id)


class _WorkspaceArtifactStore:
    def __init__(self, parent: _WorkspaceEvidenceStores) -> None: self.parent = parent
    @property
    def path(self) -> Path: return self.parent.fallback_root / ".docs" / "x20.sqlite3"
    def put(self, value: Artifact) -> None: self.parent._stores_for_root(self.parent._root_for_run(value.run_id))[1].put(value)
    def get(self, artifact_id: str) -> Any:
        for root in [self.parent._root_for_run(run.id) for run in self.parent.run_store.list()]:
            value = self.parent._stores_for_root(root)[1].get(artifact_id)
            if value is not None: return value
        return None
    def list(self) -> list[Any]:
        return [value for run in self.parent.run_store.list() for value in self.list_for_run(run.id)]
    def list_for_run(self, run_id: str) -> list[Any]: return self.parent._stores_for_root(self.parent._root_for_run(run_id))[1].list_for_run(run_id)


class _WorkspaceFindingStore:
    def __init__(self, parent: _WorkspaceEvidenceStores) -> None: self.parent = parent
    @property
    def path(self) -> Path: return self.parent.fallback_root / ".docs" / "x20.sqlite3"
    def put(self, value: dict[str, Any]) -> None: self.parent._stores_for_root(self.parent._root_for_run(str(value.get("run_id", ""))))[2].put(value)
    def list(self) -> list[dict[str, Any]]:
        return [value for run in self.parent.run_store.list() for value in self.list_for_run(run.id)]
    def list_for_run(self, run_id: str) -> list[dict[str, Any]]: return self.parent._stores_for_root(self.parent._root_for_run(run_id))[2].list_for_run(run_id)


class _WorkspacePublicationStore:
    def __init__(self, parent: _WorkspaceEvidenceStores) -> None: self.parent = parent
    @property
    def path(self) -> Path: return self.parent.fallback_root / ".docs" / "x20.sqlite3"
    def put(self, value: dict[str, Any]) -> None:
        run_id = str(value.get("run_id", ""))
        self.parent._stores_for_root(self.parent._root_for_run(run_id))[3].put(value)
    def list(self) -> list[dict[str, Any]]:
        return [value for run in self.parent.run_store.list() for value in self.parent._stores_for_root(self.parent._root_for_run(run.id))[3].list() if value.get("run_id") == run.id]


class _WorkspaceGraphStore:
    def __init__(self, registry: WorkspaceRegistry, fallback_root: Path) -> None:
        self.registry = registry
        self.fallback_root = fallback_root.resolve()

    @property
    def path(self) -> Path: return self.fallback_root / ".docs" / "x20.sqlite3"

    def _store(self, workspace_id: str | None = None) -> SqliteGraphStore:
        selected = self.registry.get(workspace_id) if workspace_id else self.registry.active()
        root = Path(str(selected["root"])).resolve() if selected is not None else self.fallback_root
        return SqliteGraphStore(root / ".docs" / "x20.sqlite3")

    def for_workspace(self, workspace_id: str) -> _WorkspaceGraphView:
        return _WorkspaceGraphView(self, workspace_id)

    def get(self, workspace_id: str | None = None) -> Any: return self._store(workspace_id).get()
    def put(self, value: Any) -> None: self._store().put(value)


class _WorkspaceGraphView:
    def __init__(self, parent: _WorkspaceGraphStore, workspace_id: str) -> None:
        self.parent = parent
        self.workspace_id = workspace_id

    def get(self) -> Any:
        return self.parent.get(self.workspace_id)

    def put(self, value: Any) -> None:
        self.parent._store(self.workspace_id).put(value)


@dataclass(frozen=True)
class SidecarConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    workspace: Path | None = None
    health_url: str = "http://127.0.0.1:8765/health"
    protocol: str = "docs-sidecar/v1"
    cors_origins: tuple[str, ...] = (
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
        "http://tauri.localhost",
    )

    @classmethod
    def from_args(cls, argv: list[str]) -> SidecarConfig:
        parser = argparse.ArgumentParser(prog="docs-sidecar")
        parser.add_argument("--workspace", type=Path, default=None)
        parser.add_argument("--health-url", default=os.environ.get("DOCS_SIDECAR_HEALTH_URL", cls.health_url))
        args = parser.parse_args(argv)
        parsed = urlsplit(args.health_url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("--health-url must be an http URL bound to 127.0.0.1")
        if parsed.path != "/health" or parsed.query or parsed.fragment:
            raise ValueError("--health-url must end with the path /health")
        return cls(
            host="127.0.0.1",
            port=parsed.port or 8765,
            workspace=args.workspace or _workspace_from_environment(),
            health_url=args.health_url,
            cors_origins=tuple(
                origin.strip().rstrip("/")
                for origin in os.environ.get(
                    "DOCS_SIDECAR_CORS_ORIGINS",
                    ",".join(cls.cors_origins),
                ).split(",")
                if origin.strip()
            ),
        )


class _HealthApplication:
    def __init__(
        self,
        application: X20Application | None,
        health_path: str,
        protocol: str,
        *,
        workspace_error: str | None = None,
        worker_runner: WorkerRunner | None = None,
        worker_thread: threading.Thread | None = None,
    ) -> None:
        self.application = application
        self.health_path = health_path
        self.protocol = protocol
        self.workspace_error = workspace_error
        self.worker_runner = worker_runner
        self.worker_thread = worker_thread

    def shutdown(self) -> None:
        if self.worker_runner is not None:
            self.worker_runner.stop()
        if self.worker_thread is not None and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        if environ.get("PATH_INFO") == self.health_path and environ.get("REQUEST_METHOD", "GET") == "GET":
            ready = self.workspace_error is None and (
                self.worker_thread is None or self.worker_thread.is_alive()
            )
            response = Response.json(
                {"ready": ready, "protocol": self.protocol}
                if ready
                else {
                    "error": self.workspace_error or "worker_not_running",
                    "protocol": self.protocol,
                    "ready": False,
                }
            )
            start_response(
                "200 OK" if ready else "503 Service Unavailable",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(response.body))),
                    ("Connection", "close"),
                ],
            )
            return [response.body]
        if self.application is None:
            response = Response.json({"error": self.workspace_error or "sidecar_unavailable"})
            start_response(
                "503 Service Unavailable",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(response.body))),
                    ("Connection", "close"),
                ],
            )
            return [response.body]
        return self.application(environ, start_response)


def _workspace_from_environment() -> Path | None:
    value = os.environ.get("DOCS_SIDECAR_WORKSPACE") or os.environ.get("DOCS_DOCUMENTS_DIR")
    return Path(value) if value else None


def build_application(config: SidecarConfig) -> _HealthApplication:
    if config.workspace is None:
        return _HealthApplication(
            None,
            urlsplit(config.health_url).path,
            config.protocol,
            workspace_error="workspace_not_configured",
        )
    registry = WorkspaceRegistry(config.workspace / ".docs" / "workspaces.json")
    configured_workspace = registry.ensure("Local workspace", config.workspace)
    if registry.active() is None:
        registry.select(configured_workspace["id"])
    state_path = config.workspace / ".docs" / "x20.sqlite3"
    run_store = _WorkspaceRunStore(registry, config.workspace)
    queue = _WorkspaceJobQueue(registry, config.workspace)
    evidence_stores = _WorkspaceEvidenceStores(registry, run_store, config.workspace)
    passport_store = evidence_stores.passport()
    artifact_store = evidence_stores.artifact()
    graph_store = _WorkspaceGraphStore(registry, config.workspace)
    findings_store = evidence_stores.finding()
    publication_store = evidence_stores.publication()
    publication_store = evidence_stores.publication()
    plugin_registry = PluginRegistry()
    plugin_roots = [config.workspace / ".docs" / "plugins"]
    for workspace_entry in registry.list():
        plugin_roots.append(Path(str(workspace_entry["root"])) / ".docs" / "plugins")
    plugin_registry.discover(plugin_roots)
    def create_document(workspace_root: str, document_id: str, template: str, title: str) -> dict[str, Any]:
        from .cli._shared import Deps
        from .domain.workspace import Workspace

        deps = Deps(Workspace(Path(workspace_root) / "documents", Path(workspace_root) / "templates"))
        document = deps.documents.create(document_id, template, title)
        return document.model_dump()

    def document_action(workspace_root: str, document_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        from .cli._shared import Deps
        from .cli.commands.document_app import _source_pipeline, create_document_service
        from .domain.workspace import Workspace

        deps = Deps(Workspace(Path(workspace_root) / "documents", Path(workspace_root) / "templates"))
        resolved = deps.resolve_context(document_id)
        if action == "prepare":
            pipeline = _source_pipeline(deps)
            if pipeline is None:
                raise RuntimeError("source pipeline dependencies are unavailable")
            return pipeline.prepare(document_id, deps.workspace.doc_root(document_id), resolved.config)
        pipeline_id = "document" if action == "build" else "document-verify"
        run_id = str(payload.get("run_id") or f"api-{action}-{uuid4().hex}")
        service = create_document_service(
            deps,
            output_format=str(payload.get("format", "docx")),
            document=document_id,
            pipeline_id=pipeline_id,
            provenance_run_id=run_id,
        )
        report = service.run(run_id, publish=action == "build", pipeline_id=pipeline_id)
        return report.to_dict()

    application = X20Application(
        run_store=run_store,
        queue=queue,
        passport_store=passport_store,
        artifact_store=artifact_store,
        graph_store=graph_store,
        plugin_registry=plugin_registry,
        findings_store=findings_store,
        publication_store=publication_store,
        document_store=_FilesystemDocumentStore(config.workspace, registry),
        workspace_registry=registry,
        document_creator=create_document,
        document_action=document_action,
        router=Router(cors_origins=config.cors_origins),
    )
    runner = _build_worker(config.workspace, queue, state_path, run_store, passport_store, artifact_store, findings_store, publication_store)
    thread = threading.Thread(target=runner.run_until_stopped, name="docs-worker", daemon=True)
    thread.start()
    return _HealthApplication(
        application,
        urlsplit(config.health_url).path,
        config.protocol,
        worker_runner=runner,
        worker_thread=thread,
    )


def _build_worker(
    workspace: Path,
    queue: SqliteJobQueue,
    state_path: Path,
    run_store: SqliteRunStore,
    passport_store: SqlitePassportStore,
    artifact_store: SqliteArtifactStore,
    findings_store: SqliteFindingStore,
    publication_store: Any,
) -> WorkerRunner:
    """Compose the real local worker; no synthetic completion path is allowed."""
    from .cli._shared import Deps
    from .cli.commands.document_app import _source_pipeline, create_document_service
    from .domain.workspace import Workspace

    root = workspace.resolve()
    registry = WorkspaceRegistry(root / ".docs" / "workspaces.json")

    class Runtime:
        def __init__(self, pipeline_id: str) -> None:
            self.pipeline_id = pipeline_id

        def run(self, run_id: str, *, inputs=(), outputs=(), excluded_stages=frozenset(), external_artifacts=None):
            del outputs, excluded_stages
            # The API payload is deliberately explicit: a run cannot execute
            # against an implicit or fake document.
            payload = current_payload.get(run_id, {})
            document_id = payload.get("document_id")
            if not isinstance(document_id, str) or not document_id:
                raise ValueError("document_id is required to execute a run")
            output_format = payload.get("format", "docx")
            run_root = root
            workspace_id = payload.get("workspace_id")
            if isinstance(workspace_id, str) and workspace_id:
                try:
                    selected = registry.get(workspace_id)
                except WorkspaceRegistryError:
                    # A CLI worker may use the user-level registry while the
                    # durable queue lives inside the workspace. The worker is
                    # already scoped to ``root``; never resolve an arbitrary
                    # payload path, but allow that registered identity to be
                    # processed in the current worker boundary.
                    selected = None
                if selected is not None:
                    run_root = Path(str(selected["root"])).resolve()
            def progress(stage: str, percent: int) -> None:
                existing = run_store.get(run_id)
                run_store.put(Run(
                    run_id,
                    status="running",
                    payload={**payload, "progress": {"stage": stage, "percent": percent}},
                    created_at=existing.created_at if existing is not None else "",
                ))
            progress("prepare", 10)
            deps = Deps(Workspace(run_root / "documents", run_root / "templates"))
            source_pipeline = _source_pipeline(deps)
            if source_pipeline is None:
                raise RuntimeError("source pipeline dependencies are unavailable")
            prepared = source_pipeline.prepare(document_id, deps.workspace.doc_root(document_id), deps.resolve_context(document_id).config)
            if not prepared.get("succeeded", False):
                raise RuntimeError("document preparation failed; inspect intake evidence")
            progress("pipeline", 35)
            service = create_document_service(
                deps,
                output_format=output_format,
                document=document_id,
                pipeline_id=self.pipeline_id,
                provenance_run_id=run_id,
            )
            policy = str(payload.get("policy", "release"))
            report = service.run(
                run_id,
                inputs=inputs,
                publish=policy != "draft",
                pipeline_id=self.pipeline_id,
                external_artifacts=external_artifacts,
            )
            progress("finalize", 90)
            if not getattr(report, "succeeded", False):
                raise RuntimeError("document pipeline failed; inspect run evidence for stage findings")
            if self.pipeline_id == "document-publish":
                publication_store.put({
                    "id": run_id,
                    "run_id": run_id,
                    "document_id": document_id,
                    "workspace_id": workspace_id,
                    "environment": str(payload.get("environment", "local")),
                    "artifact": document_id,
                    "published_at": datetime.now(UTC).isoformat(),
                    "approver": str(payload.get("approver", "local-worker")),
                    "status": "passed",
                })
            return {
                "pipeline_id": self.pipeline_id,
                "document_id": document_id,
                "succeeded": True,
                "report": report.to_dict(),
            }

    current_payload: dict[str, dict[str, Any]] = {}

    def factory(pipeline_id: str) -> Runtime:
        return Runtime(pipeline_id)

    # The worker handler needs the immutable payload for document_id while
    # still receiving the validated paths from WorkerComposition.
    composition = WorkerComposition(
        factory,
        root,
        queue,
        SqliteLeaseStore(state_path),
        run_store=run_store,
        passport_store=passport_store,
        finalizer=lambda result: _persist_worker_evidence(passport_store, artifact_store, findings_store, result),
    )
    original_handle = composition.handle

    def handle(job, scratch=None):
        current_payload[str(job.payload.get("run_id", job.id))] = dict(job.payload)
        return original_handle(job, scratch)

    composition.handle = handle  # type: ignore[method-assign]
    return WorkerRunner(composition.create_service(), poll_interval=0.2)


def _persist_worker_evidence(passport_store: SqlitePassportStore, artifact_store: SqliteArtifactStore, findings_store: SqliteFindingStore, result: Any) -> None:
    """Persist the real pipeline result as the run's durable evidence passport."""
    value = result.value if isinstance(result.value, dict) else {"value": result.value}
    passport_store.put(Passport(result.run_id, entries=(
        {"stage": "worker", "status": result.state, "attempt": result.attempt},
        {"stage": "pipeline", "result": value},
    )))
    report = value.get("report", {}) if isinstance(value, dict) else {}
    execution = report.get("execution", {}) if isinstance(report, dict) else {}
    for stage in execution.get("results", []) if isinstance(execution, dict) else []:
        if not isinstance(stage, dict):
            continue
        for index, produced in enumerate(stage.get("artifacts", ())):
            encoded = str(produced).encode("utf-8")
            digest = hashlib.sha256(encoded).hexdigest()
            artifact_store.put(Artifact(
                id=f"{result.run_id}-{stage.get('stage', 'stage')}-{index}",
                run_id=result.run_id,
                kind=str(stage.get("stage", "artifact")),
                digest=digest,
                metadata={"value": str(produced), "source": "pipeline"},
            ))
        for severity, messages in (("error", stage.get("errors", ())), ("warning", stage.get("warnings", ()) )):
            for index, message in enumerate(messages):
                findings_store.put({
                    "id": f"{result.run_id}-{stage.get('stage', 'stage')}-{severity}-{index}",
                    "run_id": result.run_id,
                    "title": f"{stage.get('stage', 'stage')} {severity}",
                    "severity": "high" if severity == "error" else "medium",
                    "status": "failed" if severity == "error" else "warnings",
                    "location": str(stage.get("stage", "pipeline")),
                    "summary": str(message),
                })


def build_server(config: SidecarConfig) -> GracefulHTTPServer:
    transport = TransportConfig(
        host=config.host,
        port=config.port,
        mode="offline",
        workspace=config.workspace,
        cors_origins=config.cors_origins,
    )
    application = build_application(config)
    server = create_server(application, transport)
    server._docs_application = application  # type: ignore[attr-defined]
    return server


def run(server: GracefulHTTPServer) -> None:
    _LOG.info(json.dumps({"event": "sidecar_started", "address": server.server_address}, default=str, sort_keys=True))
    try:
        serve(server)
    finally:
        _LOG.info(json.dumps({"event": "sidecar_stopped"}, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = SidecarConfig.from_args(sys.argv[1:] if argv is None else argv)
    server = build_server(config)

    def request_shutdown(signum: int, frame: Any) -> None:
        del frame
        _LOG.info(json.dumps({"event": "sidecar_shutdown_requested", "signal": signum}, sort_keys=True))
        server.shutdown()

    previous: dict[int, Any] = {}
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            number = getattr(signal, name)
            previous[number] = signal.signal(number, request_shutdown)
    try:
        run(server)
    finally:
        application = getattr(server, "_docs_application", None)
        if application is not None:
            application.shutdown()
        for number, handler in previous.items():
            signal.signal(number, handler)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
