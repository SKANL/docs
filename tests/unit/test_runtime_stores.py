"""The composition root owns runtime-store wiring and workspace-registry lookup."""
from __future__ import annotations

from pathlib import Path

from docs.composition import (
    RuntimeStores,
    open_workspace_registry,
    resolve_runtime_root,
    resolve_workspace_registry,
    runtime_state_path,
)
from docs.infrastructure.persistence.idempotency import SqliteIdempotencyStore
from docs.infrastructure.persistence.sqlite_runtime import (
    SqliteArtifactStore,
    SqliteFindingStore,
    SqliteGraphStore,
    SqliteJobQueue,
    SqliteLeaseStore,
    SqlitePassportStore,
    SqlitePublicationStore,
    SqliteRunStore,
)


def test_runtime_state_path_is_the_single_sqlite_location(tmp_path: Path) -> None:
    assert runtime_state_path(tmp_path) == tmp_path / ".docs" / "runtime.sqlite3"


def test_registry_prefers_the_workspace_local_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DOCS_WORKSPACE_REGISTRY", str(tmp_path / "env.json"))
    local = tmp_path / ".docs" / "workspaces.json"
    local.parent.mkdir()
    local.write_text('{"schema": "docs.workspaces.v1", "workspaces": []}', encoding="utf-8")
    assert resolve_workspace_registry(tmp_path).path == local.resolve()


def test_registry_falls_back_to_the_environment_then_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DOCS_WORKSPACE_REGISTRY", str(tmp_path / "env.json"))
    assert resolve_workspace_registry(tmp_path).path == (tmp_path / "env.json").resolve()
    monkeypatch.delenv("DOCS_WORKSPACE_REGISTRY")
    assert resolve_workspace_registry(tmp_path).path == (Path.home() / ".docs" / "workspaces.json").resolve()


def test_runtime_root_is_the_active_workspace_else_the_given_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DOCS_WORKSPACE_REGISTRY", str(tmp_path / "reg" / "workspaces.json"))
    assert resolve_runtime_root(tmp_path / "ws") == (tmp_path / "ws").resolve()
    other = tmp_path / "other"
    registry = open_workspace_registry(tmp_path / "reg" / "workspaces.json")
    registry.select(str(registry.create("other", other)["id"]))
    assert resolve_runtime_root(tmp_path / "ws") == other.resolve()


def test_runtime_stores_are_lazy_and_share_one_state_file(tmp_path: Path) -> None:
    stores = RuntimeStores(tmp_path)
    assert stores.state == runtime_state_path(tmp_path)
    assert not stores.state.exists()  # constructing the bundle touches nothing
    assert isinstance(stores.runs, SqliteRunStore)
    assert stores.runs is stores.runs
    assert stores.state.is_file()
    expected = {
        "queue": SqliteJobQueue,
        "passports": SqlitePassportStore,
        "artifacts": SqliteArtifactStore,
        "findings": SqliteFindingStore,
        "publications": SqlitePublicationStore,
        "graph": SqliteGraphStore,
        "leases": SqliteLeaseStore,
        "idempotency": SqliteIdempotencyStore,
    }
    for name, kind in expected.items():
        store = getattr(stores, name)
        assert isinstance(store, kind), name
        assert store.path == stores.state
