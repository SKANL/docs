import shutil
from pathlib import Path

import pytest

from docs.domain.models.document import DocumentSummary
from docs.domain.models.template import Template
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
    return DocumentService(JsonDocumentRepository(ws), ws, clock=lambda: "2026-06-19T00:00:00")


class _NarrowPortFake:
    """Satisfies ONLY `RegistryRepository`/`DocumentRepository`/`TemplateRepository`
    -- no `workspace` attribute -- unlike `JsonDocumentRepository`, which happens
    to expose one. `DocumentService.create()` must not implicitly depend on that
    coincidence (D2, tech-debt closeout)."""

    def __init__(self) -> None:
        self.documents: dict[str, object] = {}
        self.active = ""

    # RegistryRepository
    def load_registry(self):
        raise NotImplementedError

    def save_registry(self, registry) -> None:
        raise NotImplementedError

    def active_id(self) -> str:
        return self.active

    def set_active(self, doc_id: str) -> None:
        self.active = doc_id

    def register(self, summary: DocumentSummary) -> None:
        self.documents[summary.id] = summary

    # DocumentRepository
    def read_document(self, doc_id: str):
        raise NotImplementedError

    def write_document(self, document) -> None:
        self.documents[document.id] = document

    def exists(self, doc_id: str) -> bool:
        return doc_id in self.documents

    def move(self, old_id: str, new_id: str) -> None:
        raise NotImplementedError

    def remove(self, doc_id: str) -> None:
        raise NotImplementedError

    # TemplateRepository
    def load_template(self, name: str) -> Template:
        return Template(type="generic", title="Fake Template")

    def list_templates(self) -> list[str]:
        return ["fake"]


def test_create_works_with_repository_that_has_no_workspace_attribute(tmp_path):
    # RED (D2): `DocumentLifecycleRepository` (the port `DocumentService`
    # depends on) declares no `workspace` attribute -- `create()` must not
    # reach into `self.repository.workspace` and rely on the concrete
    # `JsonDocumentRepository` happening to expose one.
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    fake_repo = _NarrowPortFake()
    service = DocumentService(fake_repo, ws)

    document = service.create("alpha", "fake")

    assert document.id == "alpha"
    for sub in ("context", "assets", "sections", "output/draft", "runs", "corrections/inbox"):
        assert (ws.doc_root("alpha") / sub).is_dir()


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


def test_rename_moves_dir_and_updates_registry(service):
    service.create("alpha", "documento-generico")
    service.rename("alpha", "gamma")
    ws = service.repository.workspace
    assert ws.doc_root("gamma").exists()
    assert not ws.doc_root("alpha").exists()
    assert service.repository.read_document("gamma").id == "gamma"
    assert service.current() == "gamma"


def test_delete_removes_and_repoints_active(service):
    service.create("alpha", "documento-generico")
    service.create("beta", "documento-generico")
    service.delete("beta")
    assert not service.repository.workspace.doc_root("beta").exists()
    assert service.current() == "alpha"


@pytest.mark.parametrize("bad_id", ["../escape", "Bad Slug", "/abs", "a/b"])
def test_use_rejects_invalid_slug(service, bad_id):
    with pytest.raises(InvalidSlugError):
        service.use(bad_id)


@pytest.mark.parametrize("bad_id", ["../escape", "Bad Slug", "/abs", "a/b"])
def test_delete_rejects_invalid_slug(service, bad_id):
    with pytest.raises(InvalidSlugError):
        service.delete(bad_id)


@pytest.mark.parametrize("bad_id", ["../escape", "Bad Slug", "/abs", "a/b"])
def test_rename_rejects_invalid_source_slug(service, bad_id):
    service.create("alpha", "documento-generico")
    with pytest.raises(InvalidSlugError):
        service.rename(bad_id, "gamma")


def test_rename_keeps_registry_sorted(service):
    service.create("alpha", "documento-generico")
    service.create("beta", "documento-generico")
    service.rename("alpha", "zeta")
    ids = [d.id for d in service.list()]
    assert ids == sorted(ids) == ["beta", "zeta"]
