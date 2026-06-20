import shutil
from pathlib import Path

import pytest

from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.domain.ports.document_repository import DocumentExistsError, DocumentNotFoundError
from docs.domain.slug import InvalidSlugError
from docs.application.documents import DocumentService

LEGACY_TEMPLATES = Path(__file__).resolve().parents[1] / "fixtures" / "templates"


@pytest.fixture
def service(tmp_path: Path) -> DocumentService:
    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("reporte-estadia-tic", "documento-generico"):
        shutil.copy(LEGACY_TEMPLATES / f"{name}.json", templates / f"{name}.json")
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=templates)
    return DocumentService(JsonDocumentRepository(ws), clock=lambda: "2026-06-19T00:00:00")


def test_create_builds_workspace_and_sets_active(service):
    doc = service.create("alpha", "reporte-estadia-tic")
    ws = service.repository.workspace
    for sub in ("context", "assets", "sections", "output/draft", "runs", "corrections/inbox"):
        assert (ws.doc_root("alpha") / sub).is_dir()
    assert doc.template == "reporte-estadia-tic"
    assert service.repository.active_id() == "alpha"


def test_create_rejects_invalid_slug(service):
    with pytest.raises(InvalidSlugError):
        service.create("Bad Slug", "documento-generico")


def test_create_twice_raises(service):
    service.create("alpha", "documento-generico")
    with pytest.raises(DocumentExistsError):
        service.create("alpha", "documento-generico")


def test_list_and_current_and_use(service):
    service.create("alpha", "documento-generico")
    service.create("beta", "documento-generico")
    assert [d.id for d in service.list()] == ["alpha", "beta"]
    assert service.current() == "beta"
    service.use("alpha")
    assert service.current() == "alpha"


def test_use_unknown_raises(service):
    with pytest.raises(DocumentNotFoundError):
        service.use("ghost")
