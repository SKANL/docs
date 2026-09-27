"""Desktop sidecar entrypoint for the local X20 API."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import multiprocessing
import os
import signal
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .api.application import X20Application
from .api.http import Response, Router
from .api.server import GracefulHTTPServer, TransportConfig, create_server, serve
from .application.workspaces import WorkspaceRegistry, WorkspaceRegistryError
from .composition import compose_application
from .domain.runtime_records import Artifact, Passport, Run
from .infrastructure.persistence.idempotency import SqliteIdempotencyStore
from .infrastructure.persistence.sqlite_runtime import (
    SqliteArtifactStore,
    SqliteFindingStore,
    SqliteGraphStore,
    SqliteJobQueue,
    SqliteLeaseStore,
    SqlitePassportStore,
    SqlitePublicationStore,
    SqliteRunStore,
)
from .workers.composition import compose_worker
from .workers.runner import WorkerRunner

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


class _FilesystemTemplateStore:
    """Expose the selected workspace's real template manifests to Review Studio."""

    def __init__(self, workspace: Path, registry: WorkspaceRegistry) -> None:
        self.workspace = workspace.resolve()
        self.registry = registry

    def _root(self) -> Path:
        active = self.registry.active()
        return (Path(str(active["root"])) if active is not None else self.workspace).resolve() / "templates"

    def _root_for(self, workspace_id: str | None = None) -> Path:
        if workspace_id and self.registry is not None:
            return Path(str(self.registry.get(workspace_id)["root"])).resolve() / "templates"
        return self._root()

    def list(self) -> list[dict[str, Any]]:
        return self._list_root(self._root())

    def list_for_workspace(self, workspace_id: str) -> list[dict[str, Any]]:
        return self._list_root(self._root_for(workspace_id))

    @staticmethod
    def _list_root(root: Path) -> list[dict[str, Any]]:
        if not root.is_dir():
            return []
        items: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(value, dict):
                continue
            value.setdefault("id", path.stem)
            value.setdefault("version", value.get("template_version", "1"))
            value["source_path"] = str(path)
            value["updated"] = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
            items.append(value)
        return items


class _WorkspaceJsonCollectionStore:
    """Read JSON-backed baseline/revision records without inventing rows."""

    def __init__(self, root: Path, kind: str, registry: WorkspaceRegistry | None = None) -> None:
        self.root = root.resolve()
        self.kind = kind
        self.registry = registry

    def _active_root(self) -> Path:
        if self.registry is not None:
            active = self.registry.active()
            if active is not None:
                return Path(str(active["root"])).resolve()
        return self.root

    def _root_for(self, workspace_id: str | None = None) -> Path:
        if workspace_id and self.registry is not None:
            return Path(str(self.registry.get(workspace_id)["root"])).resolve()
        return self._active_root()

    def list(self) -> list[dict[str, Any]]:
        return self._list_root(self._active_root())

    def list_for_workspace(self, workspace_id: str) -> list[dict[str, Any]]:
        return self._list_root(self._root_for(workspace_id))

    def _list_root(self, root: Path) -> list[dict[str, Any]]:
        if self.kind == "baselines":
            paths = [path for path in sorted((root / "baselines").glob("*.json")) if path.name != "active.json"]
        else:
            paths = sorted((root / "documents").glob("*/sections/_revisions/revision-log.json"))
        items: list[dict[str, Any]] = []
        for path in paths:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(value, list):
                values = value
            elif isinstance(value, dict):
                values = value.get("items", [value])
            else:
                values = []
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict):
                    record = dict(item)
                    record.setdefault("source_path", str(path))
                    record.setdefault("workspace_root", str(root))
                    items.append(record)
        return items

    def promote(self, baseline_id: str, metadata: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        """Persist an explicit active-baseline pointer atomically."""
        return self._promote_in_root(self._active_root(), baseline_id, metadata)

    def promote_for_workspace(
        self, workspace_id: str, baseline_id: str, metadata: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Promote a baseline without relying on process-global active state."""
        return self._promote_in_root(self._root_for(workspace_id), baseline_id, metadata)

    def _promote_in_root(
        self, root: Path, baseline_id: str, metadata: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Persist an active pointer under one validated workspace root."""
        if self.kind != "baselines":
            return None
        candidates = self._list_root(root)
        selected = next(
            (item for item in candidates if str(item.get("id", item.get("name", ""))) == baseline_id),
            None,
        )
        if selected is None:
            return None
        record = {**selected, "promoted": True}
        if metadata:
            record["promotion"] = dict(metadata)
        target = root / "baselines" / "active.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        return record


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
        if self.fallback_root is not None and str(self.fallback_root) not in {
            str(Path(root).resolve()) for root in roots
        }:
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
        self._stores: dict[
            str, tuple[SqlitePassportStore, SqliteArtifactStore, SqliteFindingStore, SqlitePublicationStore]
        ] = {}

    def _stores_for_root(
        self, root: str | Path
    ) -> tuple[SqlitePassportStore, SqliteArtifactStore, SqliteFindingStore, SqlitePublicationStore]:
        resolved = Path(root).expanduser().resolve()
        key = str(resolved)
        if key not in self._stores:
            state = resolved / ".docs" / "x20.sqlite3"
            self._stores[key] = (
                SqlitePassportStore(state),
                SqliteArtifactStore(state),
                SqliteFindingStore(state),
                SqlitePublicationStore(state),
            )
        return self._stores[key]

    def _root_for_run(self, run_id: str) -> Path:
        run = self.run_store.get(run_id)
        if run is not None and isinstance(run.payload, Mapping):
            workspace_id = run.payload.get("workspace_id")
            if isinstance(workspace_id, str) and workspace_id:
                try:
                    return Path(str(self.registry.get(workspace_id)["root"])).resolve()
                except Exception as exc:
                    _LOG.debug("workspace lookup failed for run %s: %s", run_id, exc)
        return self.fallback_root

    def passport(self) -> _WorkspacePassportStore:
        return _WorkspacePassportStore(self)

    def artifact(self) -> _WorkspaceArtifactStore:
        return _WorkspaceArtifactStore(self)

    def finding(self) -> _WorkspaceFindingStore:
        return _WorkspaceFindingStore(self)

    def publication(self) -> _WorkspacePublicationStore:
        return _WorkspacePublicationStore(self)


class _WorkspacePassportStore:
    def __init__(self, parent: _WorkspaceEvidenceStores) -> None:
        self.parent = parent

    @property
    def path(self) -> Path:
        return self.parent.fallback_root / ".docs" / "x20.sqlite3"

    def put(self, value: Passport) -> None:
        self.parent._stores_for_root(self.parent._root_for_run(value.run_id))[0].put(value)

    def get(self, run_id: str) -> Any:
        return self.parent._stores_for_root(self.parent._root_for_run(run_id))[0].get(run_id)


class _WorkspaceArtifactStore:
    def __init__(self, parent: _WorkspaceEvidenceStores) -> None:
        self.parent = parent

    @property
    def path(self) -> Path:
        return self.parent.fallback_root / ".docs" / "x20.sqlite3"

    def put(self, value: Artifact) -> None:
        self.parent._stores_for_root(self.parent._root_for_run(value.run_id))[1].put(value)

    def get(self, artifact_id: str) -> Any:
        for root in [self.parent._root_for_run(run.id) for run in self.parent.run_store.list()]:
            value = self.parent._stores_for_root(root)[1].get(artifact_id)
            if value is not None:
                return value
        return None

    def list(self) -> list[Any]:
        return [value for run in self.parent.run_store.list() for value in self.list_for_run(run.id)]

    def list_for_run(self, run_id: str) -> list[Any]:
        return self.parent._stores_for_root(self.parent._root_for_run(run_id))[1].list_for_run(run_id)


class _WorkspaceFindingStore:
    def __init__(self, parent: _WorkspaceEvidenceStores) -> None:
        self.parent = parent

    @property
    def path(self) -> Path:
        return self.parent.fallback_root / ".docs" / "x20.sqlite3"

    def put(self, value: dict[str, Any]) -> None:
        self.parent._stores_for_root(self.parent._root_for_run(str(value.get("run_id", ""))))[2].put(value)

    def list(self) -> list[dict[str, Any]]:
        return [value for run in self.parent.run_store.list() for value in self.list_for_run(run.id)]

    def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return self.parent._stores_for_root(self.parent._root_for_run(run_id))[2].list_for_run(run_id)


class _WorkspacePublicationStore:
    def __init__(self, parent: _WorkspaceEvidenceStores) -> None:
        self.parent = parent

    @property
    def path(self) -> Path:
        return self.parent.fallback_root / ".docs" / "x20.sqlite3"

    def put(self, value: dict[str, Any]) -> None:
        run_id = str(value.get("run_id", ""))
        self.parent._stores_for_root(self.parent._root_for_run(run_id))[3].put(value)

    def list(self) -> list[dict[str, Any]]:
        return self._list_runs(self.parent.run_store.list())

    def list_for_workspace(self, workspace_id: str) -> list[dict[str, Any]]:
        runs = [
            run
            for run in self.parent.run_store.list()
            if isinstance(run.payload, Mapping) and str(run.payload.get("workspace_id", "")) == workspace_id
        ]
        return self._list_runs(runs)

    def _list_runs(self, runs: list[Any]) -> list[dict[str, Any]]:
        return [
            value
            for run in runs
            for value in self.parent._stores_for_root(self.parent._root_for_run(run.id))[3].list()
            if value.get("run_id") == run.id
        ]


class _WorkspaceGraphStore:
    def __init__(self, registry: WorkspaceRegistry, fallback_root: Path) -> None:
        self.registry = registry
        self.fallback_root = fallback_root.resolve()

    @property
    def path(self) -> Path:
        return self.fallback_root / ".docs" / "x20.sqlite3"

    def _store(self, workspace_id: str | None = None) -> SqliteGraphStore:
        selected = self.registry.get(workspace_id) if workspace_id else self.registry.active()
        root = Path(str(selected["root"])).resolve() if selected is not None else self.fallback_root
        return SqliteGraphStore(root / ".docs" / "x20.sqlite3")

    def for_workspace(self, workspace_id: str) -> _WorkspaceGraphView:
        return _WorkspaceGraphView(self, workspace_id)

    def get(self, workspace_id: str | None = None) -> Any:
        return self._store(workspace_id).get()

    def put(self, value: Any) -> None:
        self._store().put(value)


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
    # Imports are sent as JSON/base64 by the local Review Studio client. Keep
    # the transport limit above the source-import limit while retaining an
    # explicit configurable boundary instead of silently accepting unbounded
    # request bodies.
    max_body_bytes: int = 128 * 1024 * 1024
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
            max_body_bytes=_configured_body_limit(),
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

    @property
    def auth(self) -> Any:
        """Expose the composed application's validator to docs-api transport."""
        return getattr(self.application, "auth", None)

    @auth.setter
    def auth(self, validator: Any) -> None:
        if self.application is None:
            raise RuntimeError("cannot configure auth without an application")
        self.application.auth = validator

    def shutdown(self) -> None:
        if self.worker_runner is not None:
            self.worker_runner.stop()
        if self.worker_thread is not None and self.worker_thread.is_alive():
            terminate = getattr(self.worker_thread, "terminate", None)
            if callable(terminate):
                terminate()
            self.worker_thread.join(timeout=5)

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        if environ.get("PATH_INFO") == self.health_path and environ.get("REQUEST_METHOD", "GET") == "GET":
            ready = self.workspace_error is None and (self.worker_thread is None or self.worker_thread.is_alive())
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


def _configured_body_limit() -> int:
    raw = os.environ.get("DOCS_MAX_BODY_BYTES", "").strip()
    if not raw:
        return SidecarConfig.max_body_bytes
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("DOCS_MAX_BODY_BYTES must be a positive integer") from exc
    if value <= 0:
        raise ValueError("DOCS_MAX_BODY_BYTES must be a positive integer")
    return value


def _seed_builtin_templates(workspace_root: Path) -> None:
    """Make a fresh desktop workspace immediately usable by the import UI."""
    templates = workspace_root / "templates"
    templates.mkdir(parents=True, exist_ok=True)
    if any(templates.glob("*.json")):
        return
    package = files("docs.templates.builtin")
    for entry in package.iterdir():
        if entry.name.endswith(".json"):
            (templates / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")


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
    _seed_builtin_templates(config.workspace)
    # Plugin discovery is optional and declarative: manifests are inspected
    # without importing or executing plugin code. The core remains fully
    # operational when the workspace has no plugins.
    from .plugins.registry import PluginRegistry

    plugin_registry = PluginRegistry()
    plugin_registry.discover([config.workspace / "plugins"])
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

    def create_document(workspace_root: str, document_id: str, template: str, title: str) -> dict[str, Any]:
        from .composition import compose_application
        from .domain.workspace import Workspace

        deps = compose_application(Workspace(Path(workspace_root) / "documents", Path(workspace_root) / "templates"))
        document = deps.documents.create(document_id, template, title)
        return document.model_dump()

    def document_action(workspace_root: str, document_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        from .composition import compose_application
        from .domain.workspace import Workspace

        deps = compose_application(Workspace(Path(workspace_root) / "documents", Path(workspace_root) / "templates"))
        if action == "prepare" and not (deps.workspace.doc_root(document_id) / "document.json").is_file():
            metadata_files = sorted((deps.workspace.doc_root(document_id) / "inbox").glob("*.import.json"))
            if metadata_files:
                metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
                deps.documents.create(
                    document_id,
                    str(metadata.get("template", "documento-generico")),
                    str(metadata.get("title", document_id)),
                )
        resolved = deps.resolve_context(document_id)
        if action == "prepare":
            pipeline = deps.create_source_pipeline()
            report = pipeline.prepare(document_id, deps.workspace.doc_root(document_id), resolved.config)
            if report.get("succeeded"):
                report["scaffolds"] = [
                    str(deps.section.build_section(document_id, resolved.template, section.id, resolved.config))
                    for section in resolved.template.sections
                ]
            return report
        pipeline_id = "document" if action == "build" else "document-verify"
        run_id = str(payload.get("run_id") or f"api-{action}-{uuid4().hex}")
        service = deps.create_document_pipeline_service(
            output_format=str(payload.get("format", "docx")),
            document=document_id,
            pipeline_id=pipeline_id,
            provenance_run_id=run_id,
        )
        from .application.pipeline_service import PipelineRequest

        report = service.execute(PipelineRequest(run_id=run_id, publish=action == "build", pipeline_id=pipeline_id))
        return report.to_dict()

    def document_context(workspace_root: str, document_id: str) -> dict[str, Any]:
        from .composition import compose_application
        from .domain.workspace import Workspace

        deps = compose_application(Workspace(Path(workspace_root) / "documents", Path(workspace_root) / "templates"))
        resolved = deps.resolve_context(document_id)
        statuses = deps.context.status(document_id, resolved.template)
        return {
            "document_id": document_id,
            "topics": [
                {
                    "id": item.id,
                    "title": item.title,
                    "required": item.required,
                    "exists": item.exists,
                    "missing": item.missing,
                    "fields": [
                        {"key": field.key, "label": field.label, "required": field.required}
                        for field in next(
                            (topic.fields for topic in resolved.template.context_schema.topics if topic.id == item.id),
                            (),
                        )
                    ],
                }
                for item in statuses
            ],
        }

    def set_document_context(
        document_id: str, topic: str, field: str, value: str, workspace_root: str | None = None
    ) -> dict[str, Any]:
        from .composition import compose_application
        from .domain.workspace import Workspace

        active = registry.active()
        if active is None and not workspace_root:
            raise RuntimeError("workspace_not_configured")
        root = Path(workspace_root) if workspace_root else Path(str(active["root"]))
        deps = compose_application(Workspace(root / "documents", root / "templates"))
        resolved = deps.resolve_context(document_id)
        path = deps.context.set(document_id, resolved.template, topic, value, field)
        return {"document_id": document_id, "topic": topic, "field": field, "path": str(path)}

    def revise_document(document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from .composition import compose_application
        from .domain.normative import resolve_normative_settings
        from .domain.workspace import Workspace

        active = registry.active()
        if active is None:
            raise RuntimeError("workspace_not_configured")
        root = Path(str(active["root"]))
        deps = compose_application(Workspace(root / "documents", root / "templates"))
        resolved = deps.resolve_context(document_id)
        target_id = str(payload.get("target_id") or payload.get("section_id") or payload.get("topic_id") or "")
        request = str(payload.get("request") or "API revision")
        value = payload.get("new_body", payload.get("new_value", payload.get("value")))
        if not target_id or not isinstance(value, str):
            raise ValueError("target_id and string new_body/new_value are required")
        common = {
            "config": resolved.config,
            "request": request,
            "strict": bool(payload.get("strict", False)),
            "manifest_exists": False,
            "manifest_size": 0,
            "normative": resolve_normative_settings(resolved.config),
            "now": datetime.now(UTC).isoformat(),
        }
        target_kind = deps.revision.resolve_target(resolved.template, target_id)
        if target_kind == "topic":
            result = deps.revision.revise_topic(
                document_id,
                resolved.template,
                **common,
                topic_id=target_id,
                new_value=value,
                field=str(payload.get("field", "")),
            )
        else:
            result = deps.revision.revise(
                document_id, resolved.template, **common, section_id=target_id, new_body=value
            )
        return result.to_dict()

    def document_classification(document_id: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        """Expose the real ingest classification queue to every client surface."""
        active = registry.active()
        if active is None:
            raise RuntimeError("workspace_not_configured")
        queue_path = Path(str(active["root"])) / "documents" / document_id / "inbox" / "_classification-queue.json"
        if not queue_path.is_file():
            raise FileNotFoundError("classification queue is not available; run import or prepare first")
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        entries = queue if isinstance(queue, list) else queue.get("items", queue.get("sources", []))
        if payload is not None:
            relative_path = str(payload.get("relative_path", ""))
            role = str(payload.get("confirmed_role", ""))
            if not relative_path or role not in {"evidence", "example", "normative"}:
                raise ValueError("relative_path and confirmed_role (evidence, example, or normative) are required")
            matched = next((entry for entry in entries if str(entry.get("relative_path")) == relative_path), None)
            if matched is None:
                raise ValueError("classification source was not found")
            matched["confirmed_role"] = role
            queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"document_id": document_id, "items": entries}

    application = X20Application(
        run_store=run_store,
        queue=queue,
        passport_store=passport_store,
        artifact_store=artifact_store,
        graph_store=graph_store,
        # The core sidecar remains plugin-independent. Plugin discovery is an
        # optional application concern and must never be required to start or
        # execute the document pipeline.
        plugin_registry=plugin_registry,
        findings_store=findings_store,
        publication_store=publication_store,
        template_store=_FilesystemTemplateStore(config.workspace, registry),
        baseline_store=_WorkspaceJsonCollectionStore(config.workspace, "baselines", registry),
        revision_store=_WorkspaceJsonCollectionStore(config.workspace, "revisions", registry),
        document_store=_FilesystemDocumentStore(config.workspace, registry),
        workspace_registry=registry,
        managed_workspace_root=config.workspace / ".docs" / "workspaces",
        document_creator=create_document,
        document_action=document_action,
        document_context_reader=lambda document_id, workspace_root=None: document_context(
            str(workspace_root or registry.get(registry.active()["id"])["root"]), document_id
        ),
        document_context_writer=set_document_context,
        revision_service=revise_document,
        classification_service=document_classification,
        router=Router(
            cors_origins=config.cors_origins,
            max_body_size=config.max_body_bytes,
            idempotency_persistence=SqliteIdempotencyStore(state_path),
        ),
    )
    # Heavy document work runs in a separate process. A Python thread would
    # share the GIL with HTML/PDF parsing and could make the API appear dead
    # while the worker is healthy but busy.
    process = multiprocessing.Process(
        target=_worker_process_main,
        args=(config.workspace,),
        name="docs-worker",
        daemon=True,
    )
    process.start()
    return _HealthApplication(
        application,
        urlsplit(config.health_url).path,
        config.protocol,
        worker_thread=process,
    )


def _worker_process_main(workspace: Path) -> None:
    root = Path(workspace).resolve()
    registry = WorkspaceRegistry(root / ".docs" / "workspaces.json")
    state_path = root / ".docs" / "x20.sqlite3"
    queue = _WorkspaceJobQueue(registry, root)
    run_store = _WorkspaceRunStore(registry, root)
    evidence = _WorkspaceEvidenceStores(registry, run_store, root)
    runner = _build_worker(
        root,
        queue,
        state_path,
        run_store,
        evidence.passport(),
        evidence.artifact(),
        evidence.finding(),
        evidence.publication(),
    )
    runner.run_until_stopped()


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
                run_store.put(
                    Run(
                        run_id,
                        status="running",
                        payload={**payload, "progress": {"stage": stage, "percent": percent}},
                        created_at=existing.created_at if existing is not None else "",
                    )
                )

            progress("prepare", 10)
            deps = compose_application(Workspace(run_root / "documents", run_root / "templates"))
            source_pipeline = deps.create_source_pipeline()
            prepared = source_pipeline.prepare(
                document_id, deps.workspace.doc_root(document_id), deps.resolve_context(document_id).config
            )
            if not prepared.get("succeeded", False):
                raise RuntimeError("document preparation failed; inspect intake evidence")
            resolved = deps.resolve_context(document_id)
            for section in resolved.template.sections:
                deps.section.build_section(document_id, resolved.template, section.id, resolved.config)
            progress("pipeline", 35)
            service = deps.create_document_pipeline_service(
                output_format=output_format,
                document=document_id,
                pipeline_id=self.pipeline_id,
                provenance_run_id=run_id,
            )
            policy = str(payload.get("policy", "release"))
            from .application.pipeline_service import PipelineRequest

            report = service.execute(
                PipelineRequest(
                    run_id=run_id,
                    inputs=tuple(inputs),
                    publish=policy != "draft",
                    pipeline_id=self.pipeline_id,
                    external_artifacts=(tuple(external_artifacts) if external_artifacts is not None else None),
                )
            )
            progress("finalize", 90)
            if not getattr(report, "succeeded", False):
                raise RuntimeError("document pipeline failed; inspect run evidence for stage findings")
            if self.pipeline_id == "document-publish":
                publication_store.put(
                    {
                        "id": run_id,
                        "run_id": run_id,
                        "document_id": document_id,
                        "workspace_id": workspace_id,
                        "environment": str(payload.get("environment", "local")),
                        "artifact": document_id,
                        "published_at": datetime.now(UTC).isoformat(),
                        "approver": str(payload.get("approver", "local-worker")),
                        "status": "passed",
                    }
                )
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
    application = compose_application(Workspace(root / "documents", root / "templates"))
    composition = compose_worker(
        application,
        factory,
        root,
        queue,
        SqliteLeaseStore(state_path),
        run_store=run_store,
        passport_store=passport_store,
        finalizer=lambda result: _persist_worker_evidence(
            passport_store,
            artifact_store,
            findings_store,
            result,
            workspace_root=root,
        ),
    )
    original_handle = composition.handle

    def handle(job, scratch=None):
        current_payload[str(job.payload.get("run_id", job.id))] = dict(job.payload)
        return original_handle(job, scratch)

    composition.handle = handle  # type: ignore[method-assign]
    return WorkerRunner(composition.create_service(), poll_interval=0.2)


def _persist_worker_evidence(
    passport_store: Any,
    artifact_store: Any,
    findings_store: Any,
    result: Any,
    *,
    workspace_root: Path | None = None,
) -> None:
    """Persist the real pipeline result as the run's durable evidence passport."""
    value = result.value if isinstance(result.value, dict) else {"value": result.value}
    report = value.get("report", {}) if isinstance(value, dict) else {}
    execution = report.get("execution", {}) if isinstance(report, dict) else {}
    passport_entries: list[dict[str, Any]] = [
        {
            "stage": "worker",
            "status": result.state,
            "attempt": result.attempt,
            "retry_of": result.retry_of,
            "worker_id": result.worker_id,
        },
        {"stage": "pipeline", "result": value},
    ]
    for stage in execution.get("results", ()) if isinstance(execution, dict) else ():
        if isinstance(stage, Mapping):
            # Preserve the complete stage receipt in the immutable passport so
            # Review Studio and downstream consumers can explain what ran.
            receipt = dict(stage)
            passport_entries.append(
                {"stage": "pipeline_stage", "name": receipt.get("stage", "unknown"), "receipt": receipt}
            )
    passport_store.put(Passport(result.run_id, entries=tuple(passport_entries)))
    document_id = value.get("document_id") if isinstance(value, dict) else None
    document_root = None
    if isinstance(document_id, str) and document_id and workspace_root is not None:
        document_root = workspace_root / "documents" / document_id
    for stage in execution.get("results", []) if isinstance(execution, dict) else []:
        if not isinstance(stage, dict):
            continue
        for index, produced in enumerate(stage.get("artifacts", ())):
            record = dict(produced) if isinstance(produced, Mapping) else {"value": produced}
            raw_path = record.get("path")
            candidate = Path(str(raw_path)) if raw_path else None
            if candidate is not None and not candidate.is_absolute() and workspace_root is not None:
                # Pipeline stage receipts are relative to the document's
                # durable run directory, while externally published outputs
                # may be relative to the workspace. Resolve the document
                # boundary first, then retain the workspace fallback.
                document_candidate = document_root / candidate if document_root is not None else None
                candidate = (
                    document_candidate
                    if document_candidate is not None and document_candidate.is_file()
                    else workspace_root / candidate
                )
            materialized = candidate is not None and candidate.is_file()
            if materialized:
                digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                record["size_bytes"] = candidate.stat().st_size
            else:
                encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
                digest = hashlib.sha256(encoded).hexdigest()
            artifact_store.put(
                Artifact(
                    id=f"{result.run_id}-{stage.get('stage', 'stage')}-{index}",
                    run_id=result.run_id,
                    kind=str(stage.get("stage", "artifact")),
                    digest=digest,
                    media_type=str(record.get("media_type", "")),
                    metadata={"value": record, "source": "pipeline", "materialized": materialized},
                )
            )
        for severity, messages in (("error", stage.get("errors", ())), ("warning", stage.get("warnings", ()))):
            for index, message in enumerate(messages):
                findings_store.put(
                    {
                        "id": f"{result.run_id}-{stage.get('stage', 'stage')}-{severity}-{index}",
                        "run_id": result.run_id,
                        "title": f"{stage.get('stage', 'stage')} {severity}",
                        "severity": "high" if severity == "error" else "medium",
                        "status": "failed" if severity == "error" else "warnings",
                        "location": str(stage.get("stage", "pipeline")),
                        "summary": str(message),
                    }
                )


def build_server(config: SidecarConfig) -> GracefulHTTPServer:
    transport = TransportConfig(
        host=config.host,
        port=config.port,
        mode="offline",
        workspace=config.workspace,
        max_request_body=120 * 1024 * 1024,
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
    multiprocessing.freeze_support()
    # A desktop/self-hosted sidecar must remain responsive when Java is
    # installed but the optional OpenDataLoader JVM bridge stalls. The
    # pypdfium2 text-layer path is deterministic and is the safe default for
    # the long-running server process; deployments that explicitly manage
    # the converter can opt back in with DOCS_PDF_FAST_FALLBACK=0.
    os.environ.setdefault("DOCS_PDF_FAST_FALLBACK", "1")
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
