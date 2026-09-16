"""Compile validated legacy templates into the versioned Template IR."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from docs.domain.models.template import Template
from docs.domain.pipeline_kernel import deterministic_json
from docs.domain.template_validation import validate_template

from .ir import TemplateIR, _deep_thaw
from .legacy import from_legacy_template, to_legacy_template
from .lowering import RendererLoweringMetadata


class TemplateCompilationError(ValueError):
    """Raised when a template cannot become a valid IR document."""

    def __init__(self, issues: list[Any]) -> None:
        self.issues = issues
        super().__init__("Template compilation failed: " + "; ".join(str(issue) for issue in issues))


class TemplateCompiler:
    """Stateless compiler using the existing template trust boundary."""

    def compile(self, source: Template | dict[str, Any]) -> TemplateIR:
        if isinstance(source, Template):
            template = source
            raw = from_legacy_template(source)
        else:
            raw = source

        issues = validate_template(raw)
        if any(issue.severity == "error" for issue in issues):
            raise TemplateCompilationError(issues)

        if not isinstance(source, Template):
            try:
                template = Template.model_validate(raw)
            except ValidationError as exc:
                raise TemplateCompilationError(exc.errors()) from exc

        config = from_legacy_template(template)
        return TemplateIR(
            template_type=template.type,
            title=template.title,
            project_defaults=dict(template.project_defaults),
            structure=tuple(dict(part) for part in template.structure),
            sections=tuple(section.model_dump(mode="python") for section in template.sections),
            section_contracts={key: value.model_dump(mode="python") for key, value in template.section_contracts.items()},
            context_schema=template.context_schema.model_dump(mode="python"),
            template_contract=(
                template.template_contract.model_dump(mode="python")
                if template.template_contract is not None
                else None
            ),
            legacy_config=config,
        )

    def compile_json(self, text: str) -> TemplateIR:
        try:
            source = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TemplateCompilationError([str(exc)]) from exc
        if not isinstance(source, dict):
            raise TemplateCompilationError(["Template JSON root must be an object"])
        return self.compile(source)

    def lower_renderer_metadata(self, ir: TemplateIR) -> RendererLoweringMetadata:
        contract = ir.template_contract
        if contract is None:
            return RendererLoweringMetadata()
        return RendererLoweringMetadata(
            page_geometry=dict(contract.get("page_geometry", {})),
            style_contract=dict(contract.get("style_contract", {})),
            components=tuple(dict(item) for item in contract.get("components", [])),
            editable_slots=tuple(dict(item) for item in contract.get("editable_slots", [])),
            required_assets=tuple(dict(item) for item in contract.get("required_assets", [])),
            fidelity_checks=tuple(dict(item) for item in contract.get("fidelity_checks", [])),
            allowed_degradations=tuple(contract.get("allowed_degradations", [])),
            contract_declared=True,
            contract_hash=hashlib.sha256(deterministic_json(_deep_thaw(contract)).encode()).hexdigest(),
        )


def compile_template(source: Template | dict[str, Any]) -> TemplateIR:
    return TemplateCompiler().compile(source)


def compile_template_json(text: str) -> TemplateIR:
    return TemplateCompiler().compile_json(text)


def legacy_template(ir: TemplateIR) -> Template:
    return to_legacy_template(ir)
