from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol

from docs.domain.models.document import Document, DocumentSummary
from docs.domain.ports.document_repository import DocumentExistsError, DocumentRepository
from docs.domain.ports.registry_repository import RegistryRepository
from docs.domain.ports.template_repository import TemplateRepository
from docs.domain.slug import validate_slug


class DocumentLifecycleRepository(RegistryRepository, DocumentRepository, TemplateRepository, Protocol):
    """Composed port for `DocumentService`: its lifecycle operations
    (create/list/current/use/rename/delete) genuinely span registry,
    document-content, and template access, so it depends on the union of
    the three narrow ports rather than reintroducing one fat protocol.
    Narrower consumers (e.g. `ContextService`) depend on just
    `DocumentRepository`."""


_SUBDIRS = (
    "context", "assets", "sections",
    "output/draft", "output/final", "output/qa",
    "runs", "corrections/inbox",
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class DocumentService:
    def __init__(
        self,
        repository: DocumentLifecycleRepository,
        clock: Callable[[], str] = _now,
    ) -> None:
        self.repository = repository
        self._clock = clock

    def create(self, doc_id: str, template_name: str, title: str = "") -> Document:
        validate_slug(doc_id)
        template = self.repository.load_template(template_name)
        if self.repository.exists(doc_id):
            raise DocumentExistsError(f"Document `{doc_id}` already exists.")
        doc_root = self.repository.workspace.doc_root(doc_id)
        for sub in _SUBDIRS:
            (doc_root / sub).mkdir(parents=True, exist_ok=True)
        document = Document(
            id=doc_id,
            title=title or template.title or doc_id,
            template=template_name,
            project=dict(template.project_defaults),
            structure=list(template.structure),
            overrides={},
        )
        self.repository.write_document(document)
        self.repository.register(
            DocumentSummary(
                id=doc_id, title=document.title,
                template=template_name, created_at=self._clock(),
            )
        )
        return document

    def list(self) -> list[DocumentSummary]:
        return self.repository.load_registry().documents

    def current(self) -> str:
        return self.repository.active_id()

    def use(self, doc_id: str) -> None:
        validate_slug(doc_id)
        self.repository.set_active(doc_id)

    def rename(self, doc_id: str, new_id: str) -> None:
        validate_slug(doc_id)
        validate_slug(new_id)
        self.repository.move(doc_id, new_id)

    def delete(self, doc_id: str) -> None:
        validate_slug(doc_id)
        self.repository.remove(doc_id)
