from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict


class Document(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    template: str
    project: dict = {}
    structure: list[dict] = []
    overrides: dict = {}

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(), ensure_ascii=False, indent=2, sort_keys=True
        )


class DocumentSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    template: str
    created_at: str = ""
