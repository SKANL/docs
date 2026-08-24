from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# A template is HAND-WRITTEN JSON: the primary trust boundary of this
# harness. Every model here stays permissive ON PURPOSE, for two documented
# reasons that a blanket `extra="forbid"` would break:
#
#   1. `$comment` siblings. Templates document themselves inline, at the top
#      level and inside `sections[]` entries alike
#      (`test_comment_sibling_keys_are_never_treated_as_incomplete`).
#   2. Untyped passthrough on `SectionContract`. Legacy contract keys survive
#      `model_dump()` into the rendered context pack, so the agent still sees
#      them (`test_pack_context_section_contract_model_dump_surfaces_extra_keys`).
#
# The real hazard permissiveness creates -- a TYPO like `required_contents`
# being accepted and silently ignored, so the author's rule never runs while
# the template still validates -- is caught where it belongs instead:
# `template_validation._check_near_miss_keys` reports an unknown key that is
# one edit away from a real field, and says which field it meant. Precise
# enough to stay quiet for deliberate passthrough, loud enough for a typo.
_PERMISSIVE = ConfigDict(extra="allow")


class Field(BaseModel):
    model_config = _PERMISSIVE
    key: str
    label: str
    required: bool = False
    sensitive: bool = False


class Topic(BaseModel):
    model_config = _PERMISSIVE
    id: str
    title: str
    required: bool = False
    multiline: bool = False
    consumed_by: list[str] = []
    fields: list[Field] = []
    prompt: str = ""


class ContextSchema(BaseModel):
    model_config = _PERMISSIVE
    topics: list[Topic] = []


class Section(BaseModel):
    model_config = _PERMISSIVE
    id: str
    title: str
    order: int = 0
    required: bool = False
    optional: bool = False


class LengthSpec(BaseModel):
    model_config = _PERMISSIVE
    min_words: int | None = None
    max_words: int | None = None
    min_pages: int | None = None
    max_pages: int | None = None
    target_pages: int | None = None


class SectionContract(BaseModel):
    model_config = _PERMISSIVE
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
    model_config = _PERMISSIVE
    enabled: bool = True
    style: str = "APA 7"
    # spec: template-provisioning — "`citation_style` MUST accept `apa7` or
    # `none`, with only `apa7` implemented (a seam for future styles)".
    # It reached `resolve_normative_settings` only via `extra="allow"`, so a
    # spec-declared contract field was surviving as an unmodelled leftover
    # (and `citation_stile` would have been accepted just as happily).
    citation_style: str = "apa7"
    in_text_citation: str = ""
    requires_reference_for_each_citation: bool = True
    requires_citation_for_each_reference: bool = True
    reference_order: str = "alphabetical"
    reference_hanging_indent_cm: float = 1.27
    direct_quote_requires_locator: bool = True
    allowed_reference_heading: str = "REFERENCIAS"


class StrictPolicyBlock(BaseModel):
    model_config = _PERMISSIVE
    allow_pending: bool = True
    length_violations: str = "warning"
    missing_evidence: str = "warning"
    apa_violations: str = "warning"


class StrictPolicy(BaseModel):
    model_config = _PERMISSIVE
    draft: StrictPolicyBlock = StrictPolicyBlock()
    strict: StrictPolicyBlock = StrictPolicyBlock(
        allow_pending=False,
        length_violations="error",
        missing_evidence="error",
        apa_violations="error",
    )


class Template(BaseModel):
    model_config = _PERMISSIVE
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
    def from_json(cls, text: str) -> Template:
        return cls.model_validate_json(text)
