"""Native declarative cover specification and deterministic slot resolution."""
from __future__ import annotations

import re
from enum import Enum
from html import escape
from pathlib import Path
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


def _standard_lookup(config: dict[str, Any], path: str) -> str:
    """Resolve canonical cover slots without requiring one config layout.

    The document configuration is intentionally allowed to retain its
    historical top-level keys.  Canonical slots provide a stable vocabulary
    while these aliases keep existing workspaces portable.
    """
    direct = _lookup(config, path)
    if direct:
        return direct
    aliases: dict[str, tuple[str, ...]] = {
        "document.title": ("title", "metadata.title"),
        "document.subtitle": ("subtitle", "metadata.subtitle"),
        "document.id": ("document_id", "id"),
        "document.version": ("version", "metadata.version"),
        "document.status": ("status", "metadata.status"),
        "author.name": ("author.name", "author", "project.author", "context.alumno.nombre"),
        "organization.name": (
            "organization.name", "organization", "project.institution", "context.institucion.nombre"
        ),
        "course.name": ("course.name", "course", "context.curso.nombre"),
        "advisor.name": ("advisor.name", "advisor", "context.alumno.asesor"),
        "date": ("date", "metadata.date"),
    }
    for candidate in aliases.get(path, ()):
        value = _lookup(config, candidate)
        if value:
            return value
    if path.startswith("custom."):
        return _lookup(config, path)
    return ""


def _resolve_value(value: Any, config: dict[str, Any]) -> str:
    if isinstance(value, dict):
        path = value.get("path", value.get("source"))
        if path:
            return _standard_lookup(config, str(path))
        if "value" in value:
            return str(value["value"])
        return ""
    value = str(value)
    if value.startswith("{{") and value.endswith("}}"):
        return _standard_lookup(config, value[2:-2].strip())
    return value


def resolve_cover_slots(spec: CoverSpec, config: dict[str, Any]) -> dict[str, str]:
    """Resolve cover slots in declared insertion order without ambient state."""
    declared = dict(spec.content)
    # `slots` is the pre-v2 spelling.  It can fill a slot omitted by the
    # declarative block, but must never override an explicit v2 value.
    declared.update({name: value for name, value in spec.slots.items() if name not in declared})
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


def _cover_asset_path(raw: Any, config: dict[str, Any]) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    paths = config.get("paths", {})
    assets_dir = Path(paths["assets_dir"]) if isinstance(paths, dict) and paths.get("assets_dir") else None
    workspace = Path(paths["workspace_root"]) if isinstance(paths, dict) and paths.get("workspace_root") else None
    candidates = []
    if assets_dir is not None:
        candidates.append(assets_dir / candidate)
        if candidate.parts and candidate.parts[0] == assets_dir.name:
            candidates.append(assets_dir.parent / candidate)
    if workspace is not None:
        candidates.append(workspace / candidate)
    candidates.append(candidate)
    return next((path for path in candidates if path.is_file()), candidates[0] if candidates else candidate)


def _asset_has_dimensions(path: Path) -> bool:
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        return False
    if path.suffix.casefold() == ".svg":
        text = path.read_text(encoding="utf-8", errors="ignore")
        return bool(re.search(r"<svg\b", text, re.IGNORECASE) and (re.search(r"\b(?:width|viewBox)=", text)))
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.width > 0 and image.height > 0
    except (ImportError, OSError, ValueError):
        return False


def cover_asset_findings(spec: CoverSpec, config: dict[str, Any]) -> list[str]:
    """Validate configured logo/hero assets before a renderer is invoked."""
    findings: list[str] = []
    for name in ("logo", "hero"):
        raw = spec.visual.get(name)
        if raw is None:
            continue
        path = _cover_asset_path(raw, config)
        if path is None or not path.is_file():
            findings.append(f"cover.missing_asset: {name}")
        elif not _asset_has_dimensions(path):
            findings.append(f"cover.invalid_asset: {name}")
    return findings


def render_cover_html(spec: CoverSpec, config: dict[str, Any]) -> str:
    """Render the same resolved slots as a self-contained HTML cover fragment."""
    variant = spec.variant.value
    lines = [f'<header class="cover cover--{variant}" role="banner">']
    for name in ("hero", "logo"):
        path = _cover_asset_path(spec.visual.get(name), config)
        if path is not None and path.is_file() and _asset_has_dimensions(path):
            lines.append(
                f'  <img class="cover__image cover__{name}" '
                f'src="{escape(path.as_posix())}" alt="{escape(name)}">'
            )
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
