import shutil
from pathlib import Path

import pytest

from docs.domain.models.document import Document, DocumentSummary
from docs.domain.workspace import Workspace
from docs.domain.workspace_format import WorkspaceFormatError, write_workspace_marker
from docs.infrastructure.persistence.json_repository import (
    DocumentNotFoundError,
    JsonDocumentRepository,
)

CURRENT_TEMPLATES = Path(__file__).resolve().parents[1] / "fixtures" / "templates"
CURRENT_UNVERSIONED = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "workspaces"
    / "legacy"
    / "current-unversioned"
)


@pytest.fixture
def repo(tmp_path: Path) -> JsonDocumentRepository:
    write_workspace_marker(tmp_path)
    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("reporte-estadia-tic", "documento-generico"):
        shutil.copy(CURRENT_TEMPLATES / f"{name}.json", templates / f"{name}.json")
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=templates)
    return JsonDocumentRepository(ws)


def test_registry_defaults_when_absent(repo):
    registry = repo.load_registry()
    assert registry.schema_version == 1 and registry.active == "" and registry.documents == []


def test_register_sets_active_and_sorts(repo):
    repo.register(DocumentSummary(id="beta", title="B", template="documento-generico", created_at="t"))
    repo.register(DocumentSummary(id="alpha", title="A", template="documento-generico", created_at="t"))
    registry = repo.load_registry()
    assert [d.id for d in registry.documents] == ["alpha", "beta"]
    assert registry.active == "alpha"


def test_registry_file_format_matches_current(repo):
    repo.register(DocumentSummary(id="alpha", title="A", template="documento-generico", created_at="t"))
    text = repo.workspace.registry_path.read_text(encoding="utf-8")
    assert text.startswith("{\n  \"active\": \"alpha\",")  # sort_keys + indent 2
    assert "\"schema\": 1" in text  # on-disk key stays "schema"


def test_write_then_read_document_roundtrip(repo):
    repo.write_document(Document(id="alpha", title="A", template="documento-generico"))
    loaded = repo.read_document("alpha")
    assert loaded.id == "alpha" and loaded.template == "documento-generico"


def test_read_missing_document_raises(repo):
    with pytest.raises(DocumentNotFoundError):
        repo.read_document("ghost")


def test_list_templates(repo):
    assert sorted(repo.list_templates()) == ["documento-generico", "reporte-estadia-tic"]


def test_repository_rejects_current_unversioned_fixture_without_mutating_it() -> None:
    before = {
        path.relative_to(CURRENT_UNVERSIONED): path.read_bytes()
        for path in CURRENT_UNVERSIONED.rglob("*")
        if path.is_file()
    }

    with pytest.raises(WorkspaceFormatError, match="workspace_marker_missing"):
        JsonDocumentRepository(
            Workspace(
                documents_dir=CURRENT_UNVERSIONED / "documents",
                templates_dir=CURRENT_UNVERSIONED / "templates",
            )
        )

    assert {
        path.relative_to(CURRENT_UNVERSIONED): path.read_bytes()
        for path in CURRENT_UNVERSIONED.rglob("*")
        if path.is_file()
    } == before


def test_malformed_document_registry_falls_back_to_empty_without_mutating_bytes(tmp_path: Path) -> None:
    write_workspace_marker(tmp_path)
    documents_dir = tmp_path / "documents"
    documents_dir.mkdir()
    registry_path = documents_dir / "registry.json"
    original = b'{"schema": 1, "documents": ['
    registry_path.write_bytes(original)
    malformed_repo = JsonDocumentRepository(
        Workspace(documents_dir=documents_dir, templates_dir=tmp_path / "templates")
    )

    registry = malformed_repo.load_registry()

    assert registry.schema_version == 1
    assert registry.active == ""
    assert registry.documents == []
    assert registry_path.read_bytes() == original


def test_repository_rejects_malformed_workspace_marker_before_any_write(tmp_path: Path) -> None:
    (tmp_path / "workspace.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(WorkspaceFormatError, match="workspace_marker_malformed"):
        JsonDocumentRepository(
            Workspace(
                root=tmp_path,
                documents_dir=tmp_path / "documents",
                templates_dir=tmp_path / "templates",
            )
        )

    assert not (tmp_path / "documents").exists()
