# src/docs/application/generate_visuals.py
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docs.application.inline_json_writer import InlineJsonWriter
from docs.domain import figure_binding, figure_catalog
from docs.domain.figure_catalog import FigureEntry
from docs.domain.ingest_naming import sha256_hex
from docs.domain.ports.image_metadata_port import ImageMetadataPort
from docs.domain.ports.ingest_artifact_writer import IngestArtifactWriter
from docs.domain.ports.svg_rasterizer_port import SvgRasterizerPort
from docs.domain.ports.visual_renderer_port import VisualRendererPort, VisualSpec
from docs.domain.svg_normalize import normalize_svg

_SPECS_NAME = "visual-specs.json"
_CATALOG_NAME = "figure-catalog.json"
_BINDINGS_NAME = "figure-bindings.json"
_REQUIRED_SPEC_FIELDS = ("label", "type", "source")


def _read_specs_fail_open(path: Path) -> list[Any]:
    """Same fail-open shape as `figure_resolver._read_json_fail_open`, but
    for `visual-specs.json`'s top-level JSON ARRAY (document-visuals spec:
    "a list of entries"), never crashing the build on an absent/malformed/
    wrong-shaped hand-authored file."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _read_json_fail_open(path: Path) -> dict[str, Any]:
    """Same fail-open shape as `figure_resolver._read_json_fail_open`, for
    the object-shaped `figure-catalog.json`/`figure-bindings.json`."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_spec(raw: Any) -> VisualSpec | None:
    """Validates one raw `visual-specs.json` entry, WARNing and returning
    `None` on any shape violation (document-visuals spec: "Malformed entry
    warns and is skipped, others still process")."""
    if not isinstance(raw, dict):
        print(
            "WARN: una entrada de visual-specs.json no es un objeto {label, type, source, "
            "caption}; se omite.",
            file=sys.stderr,
        )
        return None
    for field_name in _REQUIRED_SPEC_FIELDS:
        value = raw.get(field_name)
        if not isinstance(value, str) or not value:
            label = raw.get("label", "?")
            print(
                f"WARN: entrada de visual-specs.json (label '{label}') sin campo requerido "
                f"'{field_name}'; se omite.",
                file=sys.stderr,
            )
            return None
    caption = raw.get("caption", "")
    if not isinstance(caption, str):
        caption = ""
    return VisualSpec(label=raw["label"], type=raw["type"], source=raw["source"], caption=caption)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Temp-then-atomic-rename, same convention as
    `infrastructure/ingest/filesystem_ingest_artifact_writer.py` and
    `infrastructure/ingest/atomic_ingest_write.py` -- a failing/interrupted
    write never leaves a partial `.svg` at `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".visual-tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class GenerateVisualsResult:
    generated: int
    skipped: int


class GenerateVisualsService:
    """Renders agent-authored `visual-specs.json` entries via a `type`-keyed
    `VisualRendererPort` registry, normalizes+rasterizes each into a sibling
    `.svg`/`.png` pair under `assets_dir/figures/`, then merges the outcome
    into `figure-catalog.json` (`origin_kind="generated"`) and auto-binds
    into `figure-bindings.json` (design.md Data Flow; document-visuals
    spec). Every per-visual failure (unregistered type, malformed entry,
    renderer/rasterizer exception, un-dimensioned PNG) is caught, WARNed to
    stderr naming the cause, and skipped -- mirrors `ingest.py`'s per-item
    WARN+skip shape so one bad visual never blocks the rest or the build."""

    def __init__(
        self,
        visual_renderers: dict[str, VisualRendererPort],
        svg_rasterizer: SvgRasterizerPort,
        image_metadata: ImageMetadataPort,
        writer: IngestArtifactWriter | None = None,
    ) -> None:
        self.visual_renderers = dict(visual_renderers)
        self.svg_rasterizer = svg_rasterizer
        self.image_metadata = image_metadata
        self.writer: IngestArtifactWriter = writer or InlineJsonWriter()

    def generate(self, sections_dir: Path, assets_dir: Path) -> GenerateVisualsResult:
        sections_dir = Path(sections_dir)
        assets_dir = Path(assets_dir)

        raw_specs = _read_specs_fail_open(sections_dir / _SPECS_NAME)
        if not raw_specs:
            return GenerateVisualsResult(generated=0, skipped=0)

        skipped = 0
        specs: list[VisualSpec] = []
        for raw in raw_specs:
            spec = _parse_spec(raw)
            if spec is None:
                skipped += 1
                continue
            specs.append(spec)

        figures_dir = assets_dir / "figures"
        entries: list[FigureEntry] = []
        bindings_additions: dict[str, str] = {}
        for spec in sorted(specs, key=lambda s: s.label):
            try:
                entry = self._render_one(spec, figures_dir)
            except Exception as exc:
                # Per-visual isolation (mirrors ingest's per-item WARN+skip):
                # any unhandled failure -- e.g. an OSError writing the .svg/.png
                # to a full/read-only assets_dir -- must skip THIS visual, never
                # abort the whole multi-visual run. generate() never raises.
                print(
                    f"WARN: fallo inesperado generando el visual '{spec.label}': {exc}; se omite.",
                    file=sys.stderr,
                )
                entry = None
            if entry is None:
                skipped += 1
                continue
            entries.append(entry)
            catalog_id = f"fig-{entry.sha256[:8]}"
            if bindings_additions.get(spec.label, catalog_id) != catalog_id:
                print(
                    f"WARN: dos visuales declaran el mismo label '{spec.label}' con contenido "
                    f"distinto; se vincula el último ('{catalog_id}') y se descarta el anterior.",
                    file=sys.stderr,
                )
            bindings_additions[spec.label] = catalog_id

        if entries:
            existing_catalog = _read_json_fail_open(sections_dir / _CATALOG_NAME)
            merged_catalog = figure_catalog.merge(existing_catalog, figure_catalog.build(entries))
            self.writer.write_json(sections_dir / _CATALOG_NAME, merged_catalog)

        if bindings_additions:
            existing_bindings_doc = _read_json_fail_open(sections_dir / _BINDINGS_NAME)
            existing_bindings = existing_bindings_doc.get("bindings", {})
            if not isinstance(existing_bindings, dict):
                existing_bindings = {}
            for label, catalog_id in bindings_additions.items():
                prior = existing_bindings.get(label)
                if prior is not None and prior != catalog_id:
                    print(
                        f"WARN: el label '{label}' ya tiene un binding manual a '{prior}' en "
                        f"{_BINDINGS_NAME}; se conserva (no se sobrescribe con '{catalog_id}').",
                        file=sys.stderr,
                    )
            merged_bindings = figure_binding.merge_bindings(existing_bindings, bindings_additions)
            output_doc = dict(existing_bindings_doc)
            output_doc["bindings"] = merged_bindings
            self.writer.write_json(sections_dir / _BINDINGS_NAME, output_doc)

        return GenerateVisualsResult(generated=len(entries), skipped=skipped)

    def _render_one(self, spec: VisualSpec, figures_dir: Path) -> FigureEntry | None:
        renderer = self.visual_renderers.get(spec.type)
        if renderer is None:
            print(
                f"WARN: el tipo de visual '{spec.type}' (label '{spec.label}') no tiene un "
                "renderer registrado; se omite.",
                file=sys.stderr,
            )
            return None

        try:
            raw_svg = renderer.render(spec)
        except Exception as exc:
            print(
                f"WARN: no se pudo renderizar el visual '{spec.label}' (tipo '{spec.type}'): {exc}; "
                "se omite.",
                file=sys.stderr,
            )
            return None

        normalized = normalize_svg(raw_svg)
        stem = f"visual-{sha256_hex(normalized.encode('utf-8'))[:8]}"
        svg_path = figures_dir / f"{stem}.svg"
        png_path = figures_dir / f"{stem}.png"

        _atomic_write_bytes(svg_path, normalized.encode("utf-8"))

        try:
            self.svg_rasterizer.rasterize(svg_path, png_path)
        except Exception as exc:
            print(
                f"WARN: no se pudo rasterizar el visual '{spec.label}' a PNG: {exc}; se omite.",
                file=sys.stderr,
            )
            svg_path.unlink(missing_ok=True)  # no dejar un .svg huérfano sin PNG ni entrada de catálogo
            return None

        dims = self.image_metadata.read_dimensions(png_path)
        if dims is None:
            print(
                f"WARN: no se pudieron leer las dimensiones de la imagen generada para el visual "
                f"'{spec.label}'; se omite.",
                file=sys.stderr,
            )
            svg_path.unlink(missing_ok=True)
            png_path.unlink(missing_ok=True)
            return None
        width_px, height_px = dims

        return FigureEntry(
            sha256=sha256_hex(png_path.read_bytes()),
            width_px=width_px,
            height_px=height_px,
            origin_relative_path=f"assets/figures/{stem}.png",
            caption=spec.caption,
            source_role="",
            origin_kind="generated",
        )
