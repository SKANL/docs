"""Native declarative cover specification and deterministic slot resolution."""
from __future__ import annotations

import re
from enum import Enum
from html import escape
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CoverMode(str, Enum):
    GENERATED = "generated"
    ASSET = "asset"
    TEMPLATE = "template"
    NONE = "none"


class CoverVariant(str, Enum):
    ACADEMIC = "academic"
    INSTITUTIONAL = "institutional"
    TECHNICAL = "technical"
    MINIMAL = "minimal"
    VISUAL = "visual"
    CUSTOM = "custom"


class CoverSpec(BaseModel):
    """An opt-in cover contract; absent specs preserve legacy cover behavior."""

    model_config = ConfigDict(extra="allow")
    mode: CoverMode = CoverMode.GENERATED
    variant: CoverVariant = CoverVariant.ACADEMIC
    content: dict[str, Any] = Field(default_factory=dict)
    page: dict[str, Any] = Field(default_factory=dict)
    visual: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] = Field(default_factory=dict)
    # Legacy alias retained for early generated-cover documents.
    slots: dict[str, str] = Field(default_factory=dict)


def _lookup(config: dict[str, Any], path: str) -> str:
    value: Any = config
    for segment in path.split("."):
        if not isinstance(value, dict):
            return ""
        value = value.get(segment)
    return "" if value is None else str(value)


def _resolve_value(value: Any, config: dict[str, Any]) -> str:
    if isinstance(value, dict):
        path = value.get("path", value.get("source"))
        if path:
            return _lookup(config, str(path))
        if "value" in value:
            return str(value["value"])
        return ""
    value = str(value)
    if value.startswith("{{") and value.endswith("}}"):
        return _lookup(config, value[2:-2].strip())
    return value


def resolve_cover_slots(spec: CoverSpec, config: dict[str, Any]) -> dict[str, str]:
    """Resolve cover slots in declared insertion order without ambient state."""
    declared = dict(spec.content)
    declared.update(spec.slots)
    if not declared:
        declared = {"title": "{{title}}"}
    return {name: _resolve_value(value, config) for name, value in declared.items()}


def resolve_cover_spec(config: dict[str, Any]) -> CoverSpec | None:
    format_config = config.get("format")
    raw = format_config.get("cover") if isinstance(format_config, dict) else None
    if not isinstance(raw, dict):
        raw = config.get("cover")
    if not isinstance(raw, dict):
        return None
    return CoverSpec.model_validate(raw)


def cover_findings(spec: CoverSpec, config: dict[str, Any]) -> list[str]:
    return [f"cover.missing_slot: {name}" for name, value in resolve_cover_slots(spec, config).items() if not value]


def render_cover_html(spec: CoverSpec, config: dict[str, Any]) -> str:
    """Render the same resolved slots as a self-contained HTML cover fragment."""
    variant = spec.variant.value
    lines = [f'<header class="cover cover--{variant}" role="banner">']
    for name, value in resolve_cover_slots(spec, config).items():
        if value:
            safe_name = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "slot"
            tag = "h1" if name.lower() == "title" else "p"
            lines.append(f'  <{tag} class="cover__slot cover__{safe_name}">{escape(value)}</{tag}>')
    lines.append("</header>")
    return "\n".join(lines)


def cover_provenance(config: dict[str, Any]) -> dict[str, Any] | None:
    """Small, serializable build/status record for an opt-in generated cover."""
    spec = resolve_cover_spec(config)
    if spec is None or spec.mode is not CoverMode.GENERATED:
        return None
    slots = resolve_cover_slots(spec, config)
    return {
        "mode": spec.mode.value,
        "variant": spec.variant.value,
        "missing_slots": [name for name, value in slots.items() if not value],
    }
