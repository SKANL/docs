from __future__ import annotations

from typing import Protocol, runtime_checkable

from docs.domain.models.document import Document


class DocumentNotFoundError(Exception):
    pass


class DocumentExistsError(Exception):
    pass


@runtime_checkable
class DocumentRepository(Protocol):
    def read_document(self, doc_id: str) -> Document: ...
    def write_document(self, document: Document) -> None: ...
    def exists(self, doc_id: str) -> bool: ...
    def move(self, old_id: str, new_id: str) -> None: ...
    def remove(self, doc_id: str) -> None: ...
