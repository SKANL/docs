from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from docs.domain.models.document import Document, DocumentSummary
from docs.domain.models.template import Template


class DocumentNotFoundError(Exception):
    pass


class DocumentExistsError(Exception):
    pass


class Registry(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    schema_version: int = Field(1, alias="schema")
    active: str = ""
    documents: list[DocumentSummary] = []

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(by_alias=True), ensure_ascii=False, indent=2, sort_keys=True
        )


class DocumentRepository(Protocol):
    def load_registry(self) -> Registry: ...
    def save_registry(self, registry: Registry) -> None: ...
    def active_id(self) -> str: ...
    def set_active(self, doc_id: str) -> None: ...
    def register(self, summary: DocumentSummary) -> None: ...
    def read_document(self, doc_id: str) -> Document: ...
    def write_document(self, document: Document) -> None: ...
    def exists(self, doc_id: str) -> bool: ...
    def load_template(self, name: str) -> Template: ...
    def list_templates(self) -> list[str]: ...
