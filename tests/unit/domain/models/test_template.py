from pathlib import Path

from docs.domain.models.template import (
    Apa7Config,
    LengthSpec,
    SectionContract,
    StrictPolicy,
    StrictPolicyBlock,
    Template,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "templates"


def _load(name: str) -> Template:
    return Template.from_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_parses_sections_and_contracts():
    template = _load("reporte-estadia-tic")
    ids = {s.id for s in template.sections}
    assert "introduccion" in ids
    assert template.section_contracts["resumen"].required_content


def test_parses_context_schema_topics_and_fields():
    template = _load("reporte-estadia-tic")
    alumno = next(t for t in template.context_schema.topics if t.id == "alumno")
    assert alumno.required is True
    assert any(f.key == "nombre" and f.required for f in alumno.fields)
    assert "introduccion" in alumno.consumed_by


def test_both_templates_load():
    assert _load("reporte-estadia-tic").type == "reporte-estadia-tic"
    assert _load("documento-generico").type == "documento-generico"


def test_section_contract_pending_allowed_in_draft_defaults_to_true():
    contract = SectionContract()
    assert contract.pending_allowed_in_draft is True


def test_section_contract_has_length_and_detect_defaults():
    contract = SectionContract()
    assert contract.length == LengthSpec()
    assert contract.detect == {}


def test_length_spec_all_optional_defaults_none():
    spec = LengthSpec()
    assert spec.min_words is None
    assert spec.max_words is None
    assert spec.min_pages is None
    assert spec.max_pages is None
    assert spec.target_pages is None


def test_apa7_config_defaults():
    config = Apa7Config()
    assert config.enabled is True
    assert config.style == "APA 7"
    assert config.in_text_citation == ""
    assert config.requires_reference_for_each_citation is True
    assert config.requires_citation_for_each_reference is True
    assert config.reference_order == "alphabetical"
    assert config.reference_hanging_indent_cm == 1.27
    assert config.direct_quote_requires_locator is True
    assert config.allowed_reference_heading == "REFERENCIAS"


def test_strict_policy_block_draft_defaults():
    block = StrictPolicyBlock()
    assert block.allow_pending is True
    assert block.length_violations == "warning"
    assert block.missing_evidence == "warning"
    assert block.apa_violations == "warning"


def test_strict_policy_default_draft_and_strict_blocks_differ():
    policy = StrictPolicy()
    assert policy.draft.allow_pending is True
    assert policy.draft.length_violations == "warning"
    assert policy.strict.allow_pending is False
    assert policy.strict.length_violations == "error"
    assert policy.strict.missing_evidence == "error"
    assert policy.strict.apa_violations == "error"


def test_template_has_apa7_and_strict_policy_defaults():
    template = Template(type="x", title="X")
    assert template.apa7 == Apa7Config()
    assert template.strict_policy.draft.allow_pending is True


def test_template_models_dont_share_mutable_default_state():
    a = Template(type="a", title="A")
    b = Template(type="b", title="B")
    a.apa7.enabled = False
    assert b.apa7.enabled is True


def test_section_contract_extra_fields_allowed():
    contract = SectionContract.model_validate({"title": "x", "custom_field": "y"})
    assert contract.model_extra["custom_field"] == "y"
