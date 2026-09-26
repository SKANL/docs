from pathlib import Path

import pytest

from docs.application.workspaces import WorkspaceRegistry, WorkspaceRegistryError

CURRENT_UNVERSIONED = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "workspaces"
    / "legacy"
    / "current-unversioned"
)


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


def test_registry_renames_without_changing_root_or_id(tmp_path: Path) -> None:
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    item = registry.create("Primary", tmp_path / "one")

    renamed = registry.rename(item["id"], "Renamed")

    assert renamed["id"] == item["id"]
    assert renamed["root"] == item["root"]
    assert renamed["name"] == "Renamed"
    assert registry.list() == [renamed]


def test_registry_provisions_isolated_workspace_layout(tmp_path: Path) -> None:
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    item = registry.create("Primary", tmp_path / "one")

    expected = {"documents", "templates", "assets", "runs", "artifacts", "baselines", "passports", ".docs"}
    assert {path.name for path in Path(item["root"]).iterdir()} >= expected


def test_registry_seeds_builtin_templates_for_new_workspace(tmp_path: Path) -> None:
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    item = registry.create("Primary", tmp_path / "one")

    templates = Path(item["root"]) / "templates"
    assert (templates / "documento-generico.json").is_file()
    assert (templates / "technical-report-srs.json").is_file()
    assert (templates / "reporte-estadia-tic.json").is_file()


def test_registry_repairs_templates_when_selecting_existing_empty_workspace(tmp_path: Path) -> None:
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    item = registry.create("Primary", tmp_path / "one")
    for template in (Path(item["root"]) / "templates").glob("*.json"):
        template.unlink()

    registry.select(item["id"])

    assert (Path(item["root"]) / "templates" / "documento-generico.json").is_file()


def test_current_unversioned_fixture_has_no_workspace_format_marker() -> None:
    assert CURRENT_UNVERSIONED.is_dir()
    assert (CURRENT_UNVERSIONED / "documents" / "registry.json").is_file()
    assert (CURRENT_UNVERSIONED / "templates" / "documento-generico.json").is_file()
    assert not (CURRENT_UNVERSIONED / "workspace.json").exists()


def test_workspace_registry_rejects_malformed_json_without_mutating_source(tmp_path: Path) -> None:
    registry_path = tmp_path / "workspaces.json"
    original = b'{"active": "broken"'
    registry_path.write_bytes(original)

    with pytest.raises(WorkspaceRegistryError, match="workspace_registry_unreadable"):
        WorkspaceRegistry(registry_path).list()

    assert registry_path.read_bytes() == original
