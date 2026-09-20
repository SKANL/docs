from pathlib import Path

import pytest

from docs.application.workspaces import WorkspaceRegistry, WorkspaceRegistryError


def test_registry_persists_create_and_active_selection(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    root = tmp_path / "workspace"
    first = WorkspaceRegistry(registry_path).create("Primary", root)
    registry = WorkspaceRegistry(registry_path)

    assert registry.list() == [first]
    assert registry.select(first["id"]) == first
    assert registry.active() == first


def test_registry_rejects_invalid_name_and_duplicate(tmp_path: Path) -> None:
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    registry.create("Primary", tmp_path / "one")
    with pytest.raises(WorkspaceRegistryError, match="invalid_workspace_name"):
        registry.create("../escape", tmp_path / "two")
    with pytest.raises(WorkspaceRegistryError, match="workspace_name_conflict"):
        registry.create("Primary", tmp_path / "two")


def test_registry_delete_clears_active_workspace(tmp_path: Path) -> None:
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    item = registry.create("Primary", tmp_path / "one")
    registry.select(item["id"])
    registry.delete(item["id"])

    assert registry.list() == []
    assert registry.active() is None
    with pytest.raises(WorkspaceRegistryError, match="workspace_not_found"):
        registry.get(item["id"])
