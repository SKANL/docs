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


class LengthSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    min_words: int | None = None
    max_words: int | None = None
    min_pages: int | None = None
    max_pages: int | None = None
    target_pages: int | None = None


class SectionContract(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = ""
    required_content: list[str] = []
    evidence_required: bool = False
    apa_required: bool = False
    # Parity fix: legacy reads `contract.get("pending_allowed_in_draft", True)` —
    # an absent key is permissive. The previous `False` default here was a parity
    # bug (see Slice 3 plan, Task 4) and is corrected to `True`.
    pending_allowed_in_draft: bool = True
    length: LengthSpec = LengthSpec()
    detect: dict[str, list[str]] = {}
    toc: bool = False
    references_list: bool = False


class Apa7Config(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    style: str = "APA 7"
    in_text_citation: str = ""
    requires_reference_for_each_citation: bool = True
    requires_citation_for_each_reference: bool = True
    reference_order: str = "alphabetical"
    reference_hanging_indent_cm: float = 1.27
    direct_quote_requires_locator: bool = True
    allowed_reference_heading: str = "REFERENCIAS"


class StrictPolicyBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    allow_pending: bool = True
    length_violations: str = "warning"
    missing_evidence: str = "warning"
    apa_violations: str = "warning"


class StrictPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")
    draft: StrictPolicyBlock = StrictPolicyBlock()
    strict: StrictPolicyBlock = StrictPolicyBlock(
        allow_pending=False,
        length_violations="error",
        missing_evidence="error",
        apa_violations="error",
    )


class Template(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    title: str
    project_defaults: dict = {}
    structure: list[dict] = []
    sections: list[Section] = []
    section_contracts: dict[str, SectionContract] = {}
    context_schema: ContextSchema = ContextSchema()
    apa7: Apa7Config = Apa7Config()
    strict_policy: StrictPolicy = StrictPolicy()

    @classmethod
    def from_json(cls, text: str) -> "Template":
        return cls.model_validate_json(text)
