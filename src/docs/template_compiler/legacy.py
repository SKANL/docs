"""Compatibility lowering from Template IR to the legacy domain model."""

from __future__ import annotations

from typing import Any

from docs.domain.models.template import Template

from .ir import TemplateIR


def to_legacy_config(ir: TemplateIR) -> dict[str, Any]:
    """Return the config shape used by existing repositories and renderers."""

    return ir.to_dict()["legacy_config"]


def to_legacy_template(ir: TemplateIR) -> Template:
    """Lower without introducing IR fields into legacy serialization."""

    return Template.model_validate(to_legacy_config(ir))


def from_legacy_template(template: Template) -> dict[str, Any]:
    """Serialize exactly as current callers serialize a ``Template``."""

    return template.model_dump(exclude_none=True, mode="python")
