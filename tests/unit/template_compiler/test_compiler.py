import json
from pathlib import Path

import pytest

from docs.domain.models.template import Template
from docs.template_compiler import (
    TEMPLATE_IR_VERSION,
    RendererLoweringMetadata,
    TemplateCompilationError,
    TemplateCompiler,
    TemplateIR,
    compile_template,
    compile_template_json,
    legacy_template,
    to_legacy_config,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "templates"


def load_template(name: str) -> Template:
    return Template.from_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_compile_and_lower_builtin_template_without_changing_legacy_config():
    template = load_template("documento-generico")
    ir = compile_template(template)

    assert ir.ir_version == TEMPLATE_IR_VERSION
    assert ir.template_type == template.type
    assert to_legacy_config(ir) == template.model_dump(exclude_none=True, mode="python")
    assert legacy_template(ir).model_dump(exclude_none=True, mode="python") == to_legacy_config(ir)


def test_compile_raw_mapping_runs_existing_template_validation():
    raw = {"type": "broken", "title": "Broken", "sections": [{"id": "s", "title": "S"}]}

    with pytest.raises(TemplateCompilationError) as raised:
        compile_template(raw)

    assert any(issue.code == "template.missing_blocks" for issue in raised.value.issues)


def test_compile_json_has_a_deterministic_serialized_ir():
    source = (FIXTURES / "technical-report-srs.json").read_text(encoding="utf-8")
    first = compile_template_json(source)
    second = compile_template_json(json.dumps(json.loads(source), indent=2, ensure_ascii=False))

    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json())["ir_version"] == TEMPLATE_IR_VERSION


def test_ir_rejects_unknown_version():
    with pytest.raises(ValueError, match="Unsupported template IR version"):
        TemplateIR(ir_version="99.0", template_type="x", title="X")


def test_renderer_lowering_is_empty_when_contract_is_omitted():
    ir = compile_template(load_template("documento-generico"))

    metadata = TemplateCompiler().lower_renderer_metadata(ir)

    assert metadata == RendererLoweringMetadata()
    assert metadata.contract_declared is False


def test_renderer_lowering_preserves_contract_and_hashes_canonical_data():
    template = Template.model_validate(
        {
            "type": "contracted",
            "title": "Contracted",
            "template_contract": {
                "page_geometry": {"width": 8.5, "height": 11},
                "style_contract": {"body_font": "Aptos"},
                "components": [{"kind": "cover"}],
                "editable_slots": [{"id": "title"}],
                "required_assets": [{"id": "logo"}],
                "fidelity_checks": [{"id": "pages"}],
                "allowed_degradations": ["preview"],
            },
        }
    )
    compiler = TemplateCompiler()
    metadata = compiler.lower_renderer_metadata(compiler.compile(template))

    assert metadata.contract_declared is True
    assert metadata.page_geometry["width"] == 8.5
    assert metadata.components == ({"kind": "cover"},)
    assert metadata.contract_hash is not None
    assert len(metadata.contract_hash) == 64


def test_template_ir_deeply_freezes_nested_input_and_serialization_snapshots():
    raw = {
        "type": "immutable",
        "title": "Immutable",
        "structure": [{"parts": [{"kind": "cover"}]}],
        "sections": [],
        "section_contracts": {},
        "context_schema": {},
        "project_defaults": {"extensions": {"nested": ["before"]}},
    }
    ir = compile_template(raw)
    serialized = ir.to_json()

    with pytest.raises(TypeError):
        ir.project_defaults["extensions"] = {}
    with pytest.raises(AttributeError):
        ir.project_defaults["extensions"]["nested"].append("blocked")

    raw["structure"][0]["parts"][0]["kind"] = "changed"
    raw["project_defaults"]["extensions"]["nested"].append("after")
    snapshot = ir.to_dict()
    snapshot["structure"][0]["parts"][0]["kind"] = "changed"

    assert ir.to_json() == serialized
    assert json.loads(serialized)["structure"][0]["parts"][0]["kind"] == "cover"
    assert json.loads(ir.to_json())["project_defaults"]["extensions"]["nested"] == ["before"]


def test_template_ir_model_dump_methods_return_detached_json_native_values():
    ir = compile_template(
        {
            "type": "immutable",
            "title": "Immutable",
            "sections": [],
            "section_contracts": {},
            "context_schema": {},
            "project_defaults": {"nested": ["before"]},
        }
    )

    dumped = ir.model_dump()
    dumped["project_defaults"]["nested"].append("changed")

    assert json.loads(ir.model_dump_json()) == ir.to_dict()
    assert json.loads(ir.model_dump_json(mode="json"))["project_defaults"]["nested"] == ["before"]


def test_template_ir_model_dump_exclude_unset_preserves_fields_set():
    ir = TemplateIR(template_type="minimal", title="Minimal")

    assert ir.model_dump(exclude_unset=True) == {
        "template_type": "minimal",
        "title": "Minimal",
    }


def test_template_ir_model_copy_deep_preserves_immutable_state():
    ir = compile_template(
        {
            "type": "immutable",
            "title": "Immutable",
            "sections": [],
            "section_contracts": {},
            "context_schema": {},
            "project_defaults": {"nested": ["before"]},
        }
    )

    copied = ir.model_copy(deep=True)

    assert copied == ir
    assert copied.model_dump() == ir.model_dump()
    with pytest.raises(TypeError):
        copied.project_defaults["nested"] = ()


def test_renderer_lowering_deeply_freezes_nested_contract_and_keeps_hash_current():
    contract = {
        "page_geometry": {"margins": {"top": 1}},
        "components": [{"kind": "figure", "options": {"colors": ["blue"]}}],
    }
    template = Template.model_validate({"type": "contracted", "title": "Contracted", "template_contract": contract})
    metadata = TemplateCompiler().lower_renderer_metadata(TemplateCompiler().compile(template))
    serialized = metadata.to_json()

    with pytest.raises(TypeError):
        metadata.page_geometry["margins"] = {}
    with pytest.raises(TypeError):
        metadata.components[0]["options"]["colors"] = ()

    contract["page_geometry"]["margins"]["top"] = 99
    contract["components"][0]["options"]["colors"].append("red")
    snapshot = metadata.to_dict()
    snapshot["components"][0]["options"]["colors"].append("green")

    assert metadata.to_json() == serialized
    assert json.loads(serialized)["page_geometry"]["margins"]["top"] == 1
    assert json.loads(metadata.to_json())["components"][0]["options"]["colors"] == ["blue"]


def test_renderer_lowering_model_dump_methods_return_detached_json_native_values():
    metadata = RendererLoweringMetadata(
        page_geometry={"margins": {"top": 1}},
        components=[{"options": {"colors": ["blue"]}}],
    )

    dumped = metadata.model_dump(mode="json")
    dumped["components"][0]["options"]["colors"].append("changed")

    assert json.loads(metadata.model_dump_json()) == metadata.to_dict()
    assert json.loads(metadata.model_dump_json(indent=2))["components"][0]["options"]["colors"] == ["blue"]


def test_renderer_lowering_model_dump_and_copy_preserve_pydantic_semantics():
    metadata = RendererLoweringMetadata(contract_declared=True)

    assert metadata.model_dump(exclude_unset=True) == {"contract_declared": True}
    copied = metadata.model_copy(deep=True)
    assert copied == metadata
    assert copied.model_dump() == metadata.model_dump()


def test_contract_validation_rejects_invalid_contract_before_ir_creation():
    raw = {
        "type": "contracted",
        "title": "Contracted",
        "sections": [],
        "section_contracts": {},
        "context_schema": {},
        "template_contract": {"page_geometry": {"width": 0}},
    }

    with pytest.raises(TemplateCompilationError) as raised:
        compile_template(raw)

    assert any(issue.code == "template.contract.invalid" for issue in raised.value.issues)


def test_contract_validation_rejects_invalid_contract_on_template_input():
    template = Template.model_validate(
        {
            "type": "contracted",
            "title": "Contracted",
            "sections": [],
            "section_contracts": {},
            "context_schema": {},
            "template_contract": {"page_geometry": {"width": 0}},
        }
    )

    with pytest.raises(TemplateCompilationError) as raised:
        compile_template(template)

    assert any(issue.code == "template.contract.invalid" for issue in raised.value.issues)
