import shutil
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


def test_registry_create_writes_the_canonical_workspace_marker(tmp_path: Path) -> None:
    root = tmp_path / "workspace"

    WorkspaceRegistry(tmp_path / "registry.json").create("Primary", root)

    assert (root / "workspace.json").read_text(encoding="utf-8") == (
        '{"schema":"docs.workspace/v1"}\n'
    )


def test_registry_rejects_unversioned_workspace_without_mutating_it(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    shutil.copytree(CURRENT_UNVERSIONED, root)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(WorkspaceRegistryError, match="workspace_marker_missing"):
        WorkspaceRegistry(tmp_path / "registry.json").create("Legacy", root)

    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (root / "workspace.json").exists()


def test_registry_select_rejects_invalid_marker_before_mutating_registry_or_root(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "registry.json"
    registry = WorkspaceRegistry(registry_path)
    item = registry.create("Primary", tmp_path / "workspace")
    registry_before = registry_path.read_bytes()
    marker = Path(item["root"]) / "workspace.json"
    marker.write_text('{"schema":"docs.workspace/v2"}', encoding="utf-8")
    root_before = {
        path.relative_to(Path(item["root"])): path.read_bytes()
        for path in Path(item["root"]).rglob("*")
        if path.is_file()
    }

    with pytest.raises(WorkspaceRegistryError, match="workspace_schema_unsupported"):
        registry.select(item["id"])

    assert registry_path.read_bytes() == registry_before
    assert {
        path.relative_to(Path(item["root"])): path.read_bytes()
        for path in Path(item["root"]).rglob("*")
        if path.is_file()
    } == root_before


def test_registry_active_rejects_missing_marker_before_creating_workspace_layout(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy"
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        '{"active":"legacy-id","workspaces":['
        f'{{"id":"legacy-id","name":"Legacy","root":"{root.as_posix()}"}}]}}',
        encoding="utf-8",
    )

    with pytest.raises(WorkspaceRegistryError, match="workspace_marker_missing"):
        WorkspaceRegistry(registry_path).active()

    assert not root.exists()


def test_registry_resolve_returns_only_a_valid_canonical_workspace(tmp_path: Path) -> None:
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    item = registry.create("Primary", tmp_path / "workspace")

    assert registry.resolve(item["id"]) == item


def test_registry_resolve_rejects_missing_marker_without_mutating_root(
    tmp_path: Path,
) -> None:
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    item = registry.create("Primary", tmp_path / "workspace")
    root = Path(item["root"])
    (root / "workspace.json").unlink()
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(WorkspaceRegistryError) as captured:
        registry.resolve(item["id"])

    assert captured.value.code == "workspace_marker_missing"
    assert {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    } == before
