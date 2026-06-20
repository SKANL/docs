from __future__ import annotations

from datetime import datetime
from typing import Callable

from docs.domain.models.document import Document, DocumentSummary
from docs.domain.ports.document_repository import (
    DocumentExistsError, DocumentRepository,
)
from docs.domain.slug import validate_slug

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
        repository: DocumentRepository,
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
