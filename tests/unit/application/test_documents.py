# tests/unit/application/test_documents.py
"""Unit coverage for DocumentService.create() workspace bootstrap (spec:
document-pipeline "Document Workspace Creation Includes Ingest Inbox").
Uses a lightweight fake repository/workspace instead of the filesystem
adapter -- exercises `_SUBDIRS` in isolation (see
tests/integration/test_document_service.py for the repository-backed
integration coverage of the rest of DocumentService)."""
from __future__ import annotations

from pathlib import Path

from docs.application.documents import DocumentService
from docs.domain.models.document import DocumentSummary
from docs.domain.models.template import Template
from docs.domain.workspace import Workspace


class _NarrowPortFake:
    """Same minimal fake as test_document_service.py's
    `_NarrowPortFake` -- satisfies ONLY `RegistryRepository`/
    `DocumentRepository`/`TemplateRepository`."""

    def __init__(self) -> None:
        self.documents: dict[str, object] = {}
        self.active = ""

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

    def load_template(self, name: str) -> Template:
        return Template(type="generic", title="Fake Template")

    def list_templates(self) -> list[str]:
        return ["fake"]


def test_create_creates_inbox_directory(tmp_path: Path):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)

    document = service.create("alpha", "fake")

    assert document.id == "alpha"
    assert (ws.doc_root("alpha") / "inbox").is_dir()


def test_create_creates_inbox_assets_directory(tmp_path: Path):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)

    service.create("alpha", "fake")

    assert (ws.doc_root("alpha") / "inbox" / "assets").is_dir()


def test_create_still_creates_previously_existing_subdirectories(tmp_path: Path):
    # Regression guard: adding inbox/ must not drop any subdirectory that
    # already existed before this change.
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)

    service.create("alpha", "fake")

    for sub in ("context", "assets", "sections", "output/draft", "output/final", "output/qa", "runs", "corrections/inbox"):
        assert (ws.doc_root("alpha") / sub).is_dir()
