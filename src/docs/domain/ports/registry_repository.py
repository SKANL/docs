from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from docs.domain.models.document import DocumentSummary


class Registry(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    schema_version: int = Field(1, alias="schema")
    active: str = ""
    documents: list[DocumentSummary] = []

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(by_alias=True), ensure_ascii=False, indent=2, sort_keys=True
        )


@runtime_checkable
class RegistryRepository(Protocol):
    def load_registry(self) -> Registry: ...
    def save_registry(self, registry: Registry) -> None: ...
    def active_id(self) -> str: ...
    def set_active(self, doc_id: str) -> None: ...
    def register(self, summary: DocumentSummary) -> None: ...
