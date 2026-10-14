"""Workspace-scoped stores the sidecar hands to the API application."""

from __future__ import annotations

import json
import logging
from builtins import list as builtin_list
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docs.application.workspaces import WorkspaceRegistry
from docs.composition import RuntimeStores, atomic_write_text, runtime_state_path
from docs.domain.identity import pretty_json, read_json_object
from docs.domain.runtime_records import Artifact, Passport
from docs.sidecar.roots import PerRoot, WorkspaceRoots

LOG = logging.getLogger("docs.sidecar")


class FilesystemDocumentStore:
    """Read real document manifests for the local API; never synthesizes rows."""

    def __init__(self, workspace: Path, registry: WorkspaceRegistry | None = None) -> None:
        self.roots = WorkspaceRoots(registry, workspace)

    def _documents_root(self) -> Path:
        return self.roots.active_root() / "documents"

    def list_for_workspace(self, workspace_root: str | Path) -> list[dict[str, Any]]:
        return self._list_from_root(Path(workspace_root).expanduser().resolve() / "documents")

    @staticmethod
    def _list_from_root(root: Path) -> list[dict[str, Any]]:
        if not root.is_dir():
            return []
        items: list[dict[str, Any]] = []
        for path in sorted(root.glob("*/document.json")):
            value = read_json_object(path)
            if value is not None:
                value.setdefault("id", path.parent.name)
                items.append(value)
        return items

    def list(self) -> list[dict[str, Any]]:
        return self._list_from_root(self._documents_root())

    def get(self, document_id: str) -> dict[str, Any] | None:
        path = self._documents_root() / document_id / "document.json"
        value = read_json_object(path)
        if value is None:
            return None
        value.setdefault("id", document_id)
        return value


class FilesystemTemplateStore:
    """Expose the selected workspace's real template manifests to Review Studio."""

    def __init__(self, workspace: Path, registry: WorkspaceRegistry) -> None:
        self.roots = WorkspaceRoots(registry, workspace)

    def list(self) -> list[dict[str, Any]]:
        return self._list_root(self.roots.active_root() / "templates")

    def list_for_workspace(self, workspace_id: str) -> builtin_list[dict[str, Any]]:
        return self._list_root(self.roots.root_for(workspace_id) / "templates")

    @staticmethod
    def _list_root(root: Path) -> builtin_list[dict[str, Any]]:
        if not root.is_dir():
            return []
        items: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.json")):
            value = read_json_object(path)
            if value is None:
                continue
            value.setdefault("id", path.stem)
            value.setdefault("version", value.get("template_version", "1"))
            value["source_path"] = str(path)
            value["updated"] = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
            items.append(value)
        return items


class WorkspaceJsonCollectionStore:
    """Read JSON-backed baseline/revision records without inventing rows."""

    def __init__(self, root: Path, kind: str, registry: WorkspaceRegistry | None = None) -> None:
        self.kind = kind
        self.roots = WorkspaceRoots(registry, root)

    def list(self) -> list[dict[str, Any]]:
        return self._list_root(self.roots.active_root())

    def list_for_workspace(self, workspace_id: str) -> builtin_list[dict[str, Any]]:
        return self._list_root(self.roots.root_for(workspace_id))

    def _list_root(self, root: Path) -> builtin_list[dict[str, Any]]:
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
                values: builtin_list[Any] = value
            elif isinstance(value, dict):
                # revision logs are {schema, entries}; "items" kept for other collections
                raw_values = value.get("entries", value.get("items", [value]))
                values = raw_values if isinstance(raw_values, list) else []
            else:
                values = []
            for item in values:
                if isinstance(item, dict):
                    record = dict(item)
                    record.setdefault("source_path", str(path))
                    record.setdefault("workspace_root", str(root))
                    items.append(record)
        return items

    def promote(self, baseline_id: str, metadata: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        """Persist an explicit active-baseline pointer atomically."""
        return self._promote_in_root(self.roots.active_root(), baseline_id, metadata)

    def promote_for_workspace(
        self, workspace_id: str, baseline_id: str, metadata: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Promote a baseline without relying on process-global active state."""
        return self._promote_in_root(self.roots.root_for(workspace_id), baseline_id, metadata)

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
        atomic_write_text(target, pretty_json(record) + "\n")
        return record


class WorkspaceRunStore:
    """Route durable run records to the SQLite database of their workspace."""

    def __init__(self, registry: WorkspaceRegistry, fallback_root: Path | None = None) -> None:
        self.roots = WorkspaceRoots(registry, fallback_root)
        self.fallback_root = self.roots.fallback
        self._store = PerRoot(RuntimeStores)

    @property
    def path(self) -> Path:
        if self.fallback_root is None:
            raise AttributeError("workspace run store has no fallback path")
        return runtime_state_path(self.fallback_root)

    def _all(self) -> list[Any]:
        return [self._store(root).runs for root in self.roots.all_roots()]

    def put(self, run: Any) -> None:
        workspace_id = run.payload.get("workspace_id") if isinstance(run.payload, Mapping) else None
        if isinstance(workspace_id, str) and workspace_id:
            self._store(self.roots.root_for(workspace_id)).runs.put(run)
        elif self.fallback_root is not None:
            self._store(self.fallback_root).runs.put(run)
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


class WorkspaceJobQueue:
    """Queue facade that claims work from every registered workspace."""

    def __init__(self, registry: WorkspaceRegistry, fallback_root: Path | None = None) -> None:
        self.roots = WorkspaceRoots(registry, fallback_root)
        self.fallback_root = self.roots.fallback
        self._queue = PerRoot(RuntimeStores)

    @property
    def path(self) -> Path:
        if self.fallback_root is None:
            raise AttributeError("workspace queue has no fallback path")
        return runtime_state_path(self.fallback_root)

    def enqueue(self, job_id: str, payload: dict[str, object]) -> None:
        workspace_id = payload.get("workspace_id")
        if isinstance(workspace_id, str) and workspace_id:
            self._queue(self.roots.root_for(workspace_id)).queue.enqueue(job_id, payload)
        elif self.fallback_root is not None:
            self._queue(self.fallback_root).queue.enqueue(job_id, payload)
        else:
            raise ValueError("workspace_id is required for queued runs")

    def claim(self, worker_id: str) -> Any:
        for root in self.roots.all_roots():
            job = self._queue(root).queue.claim(worker_id)
            if job is not None:
                return job
        return None

    def ack(self, job_id: str, worker_id: str) -> bool:
        return any(item.queue.ack(job_id, worker_id) for item in self._queue.values())

    def cancel(self, run_id: str) -> bool:
        return any(item.queue.cancel(run_id) for item in self._queue.values())

    def is_cancelled(self, run_id: str) -> bool:
        return any(item.queue.is_cancelled(run_id) for item in self._queue.values())


class WorkspaceEvidenceStores:
    """Route passport, artifact, and finding projections by their run owner."""

    def __init__(self, registry: WorkspaceRegistry, run_store: WorkspaceRunStore, fallback_root: Path) -> None:
        self.roots = WorkspaceRoots(registry, fallback_root)
        self.run_store = run_store
        self.fallback_root = fallback_root.resolve()
        self._stores_for_root = PerRoot(RuntimeStores)

    def _root_for_run(self, run_id: str) -> Path:
        run = self.run_store.get(run_id)
        if run is not None and isinstance(run.payload, Mapping):
            workspace_id = run.payload.get("workspace_id")
            if isinstance(workspace_id, str) and workspace_id:
                try:
                    return self.roots.root_for(workspace_id)
                except Exception as exc:
                    LOG.debug("workspace lookup failed for run %s: %s", run_id, exc)
        return self.fallback_root

    def passport(self) -> WorkspacePassportStore:
        return WorkspacePassportStore(self)

    def artifact(self) -> WorkspaceArtifactStore:
        return WorkspaceArtifactStore(self)

    def finding(self) -> WorkspaceFindingStore:
        return WorkspaceFindingStore(self)

    def publication(self) -> WorkspacePublicationStore:
        return WorkspacePublicationStore(self)


class WorkspacePassportStore:
    def __init__(self, parent: WorkspaceEvidenceStores) -> None:
        self.parent = parent

    @property
    def path(self) -> Path:
        return runtime_state_path(self.parent.fallback_root)

    def put(self, value: Passport) -> None:
        self.parent._stores_for_root(self.parent._root_for_run(value.run_id)).passports.put(value)

    def get(self, run_id: str) -> Any:
        return self.parent._stores_for_root(self.parent._root_for_run(run_id)).passports.get(run_id)


class WorkspaceArtifactStore:
    def __init__(self, parent: WorkspaceEvidenceStores) -> None:
        self.parent = parent

    @property
    def path(self) -> Path:
        return runtime_state_path(self.parent.fallback_root)

    def put(self, value: Artifact) -> None:
        self.parent._stores_for_root(self.parent._root_for_run(value.run_id)).artifacts.put(value)

    def get(self, artifact_id: str) -> Any:
        for root in [self.parent._root_for_run(run.id) for run in self.parent.run_store.list()]:
            value = self.parent._stores_for_root(root).artifacts.get(artifact_id)
            if value is not None:
                return value
        return None

    def list(self) -> list[Any]:
        return [value for run in self.parent.run_store.list() for value in self.list_for_run(run.id)]

    def list_for_run(self, run_id: str) -> builtin_list[Any]:
        return self.parent._stores_for_root(self.parent._root_for_run(run_id)).artifacts.list_for_run(run_id)


class WorkspaceFindingStore:
    def __init__(self, parent: WorkspaceEvidenceStores) -> None:
        self.parent = parent

    @property
    def path(self) -> Path:
        return runtime_state_path(self.parent.fallback_root)

    def put(self, value: dict[str, Any]) -> None:
        self.parent._stores_for_root(self.parent._root_for_run(str(value.get("run_id", "")))).findings.put(value)

    def list(self) -> list[dict[str, Any]]:
        return [value for run in self.parent.run_store.list() for value in self.list_for_run(run.id)]

    def list_for_run(self, run_id: str) -> builtin_list[dict[str, Any]]:
        return self.parent._stores_for_root(self.parent._root_for_run(run_id)).findings.list_for_run(run_id)


class WorkspacePublicationStore:
    def __init__(self, parent: WorkspaceEvidenceStores) -> None:
        self.parent = parent

    @property
    def path(self) -> Path:
        return runtime_state_path(self.parent.fallback_root)

    def put(self, value: dict[str, Any]) -> None:
        run_id = str(value.get("run_id", ""))
        self.parent._stores_for_root(self.parent._root_for_run(run_id)).publications.put(value)

    def put_if_absent(self, value: dict[str, Any]) -> bool:
        run_id = str(value.get("run_id", ""))
        return self.parent._stores_for_root(self.parent._root_for_run(run_id)).publications.put_if_absent(value)

    def list(self) -> list[dict[str, Any]]:
        return self._list_runs(self.parent.run_store.list())

    def list_for_workspace(self, workspace_id: str) -> builtin_list[dict[str, Any]]:
        runs = [
            run
            for run in self.parent.run_store.list()
            if isinstance(run.payload, Mapping) and str(run.payload.get("workspace_id", "")) == workspace_id
        ]
        return self._list_runs(runs)

    def _list_runs(self, runs: builtin_list[Any]) -> builtin_list[dict[str, Any]]:
        return [
            value
            for run in runs
            for value in self.parent._stores_for_root(self.parent._root_for_run(run.id)).publications.list()
            if value.get("run_id") == run.id
        ]


class WorkspaceGraphStore:
    def __init__(self, registry: WorkspaceRegistry, fallback_root: Path) -> None:
        self.roots = WorkspaceRoots(registry, fallback_root)
        self.fallback_root = fallback_root.resolve()
        self._graph = PerRoot(RuntimeStores)

    @property
    def path(self) -> Path:
        return runtime_state_path(self.fallback_root)

    def _store(self, workspace_id: str | None = None) -> Any:
        return self._graph(self.roots.root_for(workspace_id)).graph

    def for_workspace(self, workspace_id: str) -> WorkspaceGraphView:
        return WorkspaceGraphView(self, workspace_id)

    def get(self, workspace_id: str | None = None) -> Any:
        return self._store(workspace_id).get()

    def put(self, value: Any) -> None:
        self._store().put(value)


class WorkspaceGraphView:
    def __init__(self, parent: WorkspaceGraphStore, workspace_id: str) -> None:
        self.parent = parent
        self.workspace_id = workspace_id

    def get(self) -> Any:
        return self.parent.get(self.workspace_id)

    def put(self, value: Any) -> None:
        self.parent._store(self.workspace_id).put(value)
