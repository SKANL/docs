import shutil
from pathlib import Path

import pytest

from docs.domain.workspace import Workspace
from docs.domain.models.document import Document, DocumentSummary
from docs.infrastructure.persistence.json_repository import (
    JsonDocumentRepository, DocumentNotFoundError,
)

LEGACY_TEMPLATES = Path(__file__).resolve().parents[1] / "fixtures" / "templates"


@pytest.fixture
def repo(tmp_path: Path) -> JsonDocumentRepository:
    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("reporte-estadia-tic", "documento-generico"):
        shutil.copy(LEGACY_TEMPLATES / f"{name}.json", templates / f"{name}.json")
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


def test_registry_file_format_matches_legacy(repo):
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
