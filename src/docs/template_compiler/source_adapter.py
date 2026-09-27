"""Adapter between Template IR and the source template domain model."""

from __future__ import annotations

from typing import Any

from docs.domain.models.template import Template

from .ir import TemplateIR


def to_source_config(ir: TemplateIR) -> dict[str, Any]:
    """Return the config shape used by existing repositories and renderers."""

    return ir.to_dict()["source_config"]


def to_source_template(ir: TemplateIR) -> Template:
    """Lower without introducing IR fields into source-template serialization."""

    return Template.model_validate(to_source_config(ir))


def from_source_template(template: Template) -> dict[str, Any]:
    """Serialize exactly as current callers serialize a ``Template``."""

    return template.model_dump(exclude_none=True, mode="python")
