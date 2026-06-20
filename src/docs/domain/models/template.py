from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Field(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    label: str
    required: bool = False
    sensitive: bool = False


class Topic(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    required: bool = False
    multiline: bool = False
    consumed_by: list[str] = []
    fields: list[Field] = []
    prompt: str = ""


class ContextSchema(BaseModel):
    model_config = ConfigDict(extra="allow")
    topics: list[Topic] = []


class Section(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    order: int = 0
    required: bool = False
    optional: bool = False


class SectionContract(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = ""
    required_content: list[str] = []
    evidence_required: bool = False
    apa_required: bool = False
    pending_allowed_in_draft: bool = False


class Template(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    title: str
    project_defaults: dict = {}
    structure: list[dict] = []
    sections: list[Section] = []
    section_contracts: dict[str, SectionContract] = {}
    context_schema: ContextSchema = ContextSchema()

    @classmethod
    def from_json(cls, text: str) -> "Template":
        return cls.model_validate_json(text)
