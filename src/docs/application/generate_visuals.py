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
from docs.domain.svg_normalize import ensure_accessibility_metadata, normalize_svg

_SPECS_NAME = "visual-specs.json"
_CATALOG_NAME = "figure-catalog.json"
_BINDINGS_NAME = "figure-bindings.json"
_REQUIRED_SPEC_FIELDS = ("label", "type", "source")
_MAX_SPECS = 256
_MAX_SPECS_BYTES = 4_000_000
_MAX_TEXT_LENGTH = 1_000_000
_MAX_TOTAL_TEXT_LENGTH = 4_000_000
_MAX_RENDERED_SVG_BYTES = 4_000_000
_METADATA_FIELDS = (
    "caption",
    "accessible_name",
    "accessible_description",
    "semantic_summary",
    "unit",
    "data_fallback",
)


def _read_specs_fail_open(path: Path) -> list[Any]:
    """Same fail-open shape as `figure_resolver._read_json_fail_open`, but
    for `visual-specs.json`'s top-level JSON ARRAY (document-visuals spec:
    "a list of entries"), never crashing the build on an absent/malformed/
    wrong-shaped hand-authored file."""
    if not path.exists():
        return []
    try:
        raw_bytes = path.read_bytes()
        if len(raw_bytes) > _MAX_SPECS_BYTES:
            print(
                f"WARN: {path.name} supera el límite de {_MAX_SPECS_BYTES} bytes; se omite.",
                file=sys.stderr,
            )
            return []
        data = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"WARN: no se pudo leer {path.name}: {exc}; se omite.", file=sys.stderr)
        return []
    if not isinstance(data, list):
        print(f"WARN: {path.name} debe contener una lista; se omite.", file=sys.stderr)
        return []
    if len(data) > _MAX_SPECS:
        print(f"WARN: {path.name} supera el límite de {_MAX_SPECS} visuales; se omite.", file=sys.stderr)
        return []
    total_text_length = sum(
        len(value)
        for raw in data
        if isinstance(raw, dict)
        for field_name in (*_REQUIRED_SPEC_FIELDS, *_METADATA_FIELDS)
        for value in (raw.get(field_name),)
        if isinstance(value, str)
    )
    if total_text_length > _MAX_TOTAL_TEXT_LENGTH:
        print(
            f"WARN: {path.name} supera el límite acumulado de "
            f"{_MAX_TOTAL_TEXT_LENGTH} caracteres; se omite.",
            file=sys.stderr,
        )
        return []
    return data


def _read_json_fail_open(path: Path) -> dict[str, Any] | None:
    """Same fail-open shape as `figure_resolver._read_json_fail_open`, for
    the object-shaped `figure-catalog.json`/`figure-bindings.json`."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"WARN: no se pudo leer {path.name}: {exc}; se preserva el archivo existente.", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f"WARN: {path.name} debe contener un objeto; se preserva el archivo existente.", file=sys.stderr)
        return None
    if path.name == _CATALOG_NAME and not isinstance(data.get("figures"), list):
        print(f"WARN: {path.name} tiene una forma inválida; se preserva el archivo existente.", file=sys.stderr)
        return None
    if path.name == _BINDINGS_NAME and not isinstance(data.get("bindings"), dict):
        print(f"WARN: {path.name} tiene una forma inválida; se preserva el archivo existente.", file=sys.stderr)
        return None
    return data


def _parse_spec(raw: Any) -> VisualSpec | None:
    """Validates one raw `visual-specs.json` entry, WARNing and returning
    `None` on any shape violation (document-visuals spec: "Malformed entry
    warns and is skipped, others still process")."""
    if not isinstance(raw, dict):
        print(
            "WARN: una entrada de visual-specs.json no es un objeto {label, type, source, caption}; se omite.",
            file=sys.stderr,
        )
        return None
    for field_name in _REQUIRED_SPEC_FIELDS:
        value = raw.get(field_name)
        if not isinstance(value, str) or not value:
            label = raw.get("label", "?")
            print(
                f"WARN: entrada de visual-specs.json (label '{label}') sin campo requerido '{field_name}'; se omite.",
                file=sys.stderr,
            )
            return None
    text_fields = (*_REQUIRED_SPEC_FIELDS, *_METADATA_FIELDS)
    if any(isinstance(raw.get(field), str) and len(raw[field]) > _MAX_TEXT_LENGTH for field in text_fields):
        print(f"WARN: visual '{raw['label']}' supera el límite de entrada; se omite.", file=sys.stderr)
        return None
    caption = raw.get("caption", "")
    if not isinstance(caption, str):
        caption = ""
    name = raw.get("accessible_name", "") if isinstance(raw.get("accessible_name", ""), str) else ""
    name = name.strip() or caption.strip() or raw["label"]
    description = raw.get("accessible_description", "") if isinstance(raw.get("accessible_description", ""), str) else ""
    return VisualSpec(
        label=raw["label"],
        type=raw["type"],
        source=raw["source"],
        caption=caption,
        accessible_name=name,
        accessible_description=description.strip() or f"Generated visual: {name}.",
        unit=raw.get("unit", "") if isinstance(raw.get("unit", ""), str) else "",
        semantic_summary=(
            raw.get("semantic_summary", "")
            if isinstance(raw.get("semantic_summary", ""), str)
            else ""
        ),
        decorative=raw.get("decorative", False) if isinstance(raw.get("decorative", False), bool) else False,
        data_fallback=(
            raw.get("data_fallback", "")
            if isinstance(raw.get("data_fallback", ""), str)
            else ""
        ),
    )


def _chart_data_fallback(spec: VisualSpec) -> str:
    """Create deterministic text for chart users who cannot perceive SVG."""
    if spec.data_fallback.strip() or spec.type != "chart":
        return spec.data_fallback
    try:
        data = json.loads(spec.source)
    except (json.JSONDecodeError, TypeError):
        return ""
    labels = data.get("labels") if isinstance(data, dict) else None
    series = data.get("series") if isinstance(data, dict) else None
    if not isinstance(labels, list) or not isinstance(series, list):
        return ""
    unit = f" {spec.unit.strip()}" if spec.unit.strip() else ""
    rows = []
    for index, label in enumerate(labels):
        named_values = []
        for entry in series:
            if isinstance(entry, dict) and isinstance(entry.get("values"), list) and index < len(entry["values"]):
                series_label = str(entry.get("label", "Series"))
                named_values.append(f"{series_label}={entry['values'][index]}")
        rows.append(f"{label}: {', '.join(named_values)}{unit}")
    return "; ".join(rows)


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


def _publish_pair(svg_path: Path, png_path: Path, svg_bytes: bytes, png_bytes: bytes) -> None:
    """Publish an SVG/PNG pair as one transaction.

    Both outputs are staged before either final path is changed. Existing
    outputs are moved aside while the pair is published and restored if any
    publication step fails, so a failed second rename cannot leave a
    mismatched or orphaned pair.
    """
    parent = svg_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    backup_paths: dict[Path, Path] = {}
    with tempfile.TemporaryDirectory(dir=parent.parent, prefix=".visual-publish-") as temp_dir:
        temp_root = Path(temp_dir)
        try:
            for final_path in (svg_path, png_path):
                if final_path.exists():
                    backup_path = temp_root / final_path.name
                    os.replace(final_path, backup_path)
                    backup_paths[final_path] = backup_path

            _atomic_write_bytes(svg_path, svg_bytes)
            _atomic_write_bytes(png_path, png_bytes)
        except BaseException:
            for final_path in (svg_path, png_path):
                final_path.unlink(missing_ok=True)
            for final_path, backup_path in backup_paths.items():
                os.replace(backup_path, final_path)
            raise


@dataclass(frozen=True)
class GenerateVisualsResult:
    generated: int
    skipped: int
    generated_labels: tuple[str, ...] = ()
    skipped_labels: tuple[str, ...] = ()
    generated_visuals: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "generated": self.generated,
            "skipped": self.skipped,
            "generated_labels": list(self.generated_labels),
            "skipped_labels": list(self.skipped_labels),
            "generated_visuals": [dict(item) for item in self.generated_visuals],
        }


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
            self.writer.write_json(
                sections_dir / "visual-generation-report.json",
                GenerateVisualsResult(generated=0, skipped=0).to_dict(),
            )
            return GenerateVisualsResult(generated=0, skipped=0)

        skipped = 0
        skipped_labels: list[str] = []
        specs: list[VisualSpec] = []
        for raw in raw_specs:
            spec = _parse_spec(raw)
            if spec is None:
                skipped += 1
                skipped_labels.append(str(raw.get("label", "?")) if isinstance(raw, dict) else "?")
                continue
            specs.append(spec)

        catalog_path = sections_dir / _CATALOG_NAME
        bindings_path = sections_dir / _BINDINGS_NAME
        existing_catalog = _read_json_fail_open(catalog_path)
        existing_bindings_doc = _read_json_fail_open(bindings_path)
        if existing_catalog is None or existing_bindings_doc is None:
            result = GenerateVisualsResult(
                generated=0,
                skipped=skipped + len(specs),
                skipped_labels=tuple(sorted(skipped_labels + [spec.label for spec in specs])),
            )
            self.writer.write_json(sections_dir / "visual-generation-report.json", result.to_dict())
            return result

        figures_dir = assets_dir / "figures"
        entries: list[FigureEntry] = []
        bindings_additions: dict[str, str] = {}
        generated_visuals: list[dict[str, str]] = []
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
                skipped_labels.append(spec.label)
                continue
            entries.append(entry)
            generated_visuals.append(
                {
                    "label": spec.label,
                    "type": spec.type,
                    "source_sha256": sha256_hex(spec.source.encode("utf-8")),
                    "asset_sha256": entry.sha256,
                }
            )
            catalog_id = f"fig-{entry.sha256[:8]}"
            if bindings_additions.get(spec.label, catalog_id) != catalog_id:
                print(
                    f"WARN: dos visuales declaran el mismo label '{spec.label}' con contenido "
                    f"distinto; se vincula el último ('{catalog_id}') y se descarta el anterior.",
                    file=sys.stderr,
                )
            bindings_additions[spec.label] = catalog_id

        if entries:
            merged_catalog = figure_catalog.merge(existing_catalog, figure_catalog.build(entries))
            self.writer.write_json(catalog_path, merged_catalog)

        if bindings_additions:
            existing_bindings = existing_bindings_doc.get("bindings", {})
            for label, catalog_id in bindings_additions.items():
                current = existing_bindings.get(label)
                if current is not None and current != catalog_id:
                    print(
                        f"WARN: el label '{label}' ya tiene un binding manual a '{current}' en "
                        f"{_BINDINGS_NAME}; se conserva (no se sobrescribe con '{catalog_id}').",
                        file=sys.stderr,
                    )
            merged_bindings = figure_binding.merge_bindings(existing_bindings, bindings_additions)
            output_doc = dict(existing_bindings_doc)
            output_doc["bindings"] = merged_bindings
            self.writer.write_json(bindings_path, output_doc)

        result = GenerateVisualsResult(
            generated=len(entries),
            skipped=skipped,
            generated_labels=tuple(sorted(spec.label for spec in specs if spec.label in bindings_additions)),
            skipped_labels=tuple(sorted(skipped_labels)),
            generated_visuals=tuple(generated_visuals),
        )
        self.writer.write_json(sections_dir / "visual-generation-report.json", result.to_dict())
        return result

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
                f"WARN: no se pudo renderizar el visual '{spec.label}' (tipo '{spec.type}'): {exc}; se omite.",
                file=sys.stderr,
            )
            return None

        if not isinstance(raw_svg, str):
            raise ValueError("renderer output is not text")
        normalized = normalize_svg(raw_svg)
        with_metadata = ensure_accessibility_metadata(
            normalized,
            spec.accessible_name,
            spec.accessible_description,
            decorative=spec.decorative,
        )
        final_svg_bytes = normalize_svg(with_metadata).encode("utf-8")
        if len(final_svg_bytes) > _MAX_RENDERED_SVG_BYTES:
            raise ValueError(f"renderer output exceeds {_MAX_RENDERED_SVG_BYTES} bytes")
        stem = f"visual-{sha256_hex(final_svg_bytes)[:8]}"
        svg_path = figures_dir / f"{stem}.svg"
        png_path = figures_dir / f"{stem}.png"

        try:
            figures_dir.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=figures_dir.parent, prefix=".visual-") as temp_dir:
                temp_svg_path = Path(temp_dir) / f"{stem}.svg"
                temp_png_path = Path(temp_dir) / f"{stem}.png"
                temp_svg_path.write_bytes(final_svg_bytes)
                self.svg_rasterizer.rasterize(temp_svg_path, temp_png_path)
                dims = self.image_metadata.read_dimensions(temp_png_path)
                if dims is None:
                    raise ValueError("no se pudieron leer las dimensiones")
                width_px, height_px = dims
                png_bytes = temp_png_path.read_bytes()

            # Publish only after rendering, metadata inspection, and complete
            # PNG reads succeed. Pair publication rolls back if either output
            # fails, so failed reruns touch no final pair.
            _publish_pair(svg_path, png_path, final_svg_bytes, png_bytes)
        except Exception as exc:
            print(
                f"WARN: no se pudo completar el visual '{spec.label}': {exc}; se omite.",
                file=sys.stderr,
            )
            return None

        return FigureEntry(
            sha256=sha256_hex(png_bytes),
            width_px=width_px,
            height_px=height_px,
            origin_relative_path=f"assets/figures/{stem}.png",
            caption=spec.caption,
            source_role="",
            origin_kind="generated",
            accessible_name=spec.accessible_name,
            accessible_description=spec.accessible_description,
            unit=spec.unit,
            semantic_summary=spec.semantic_summary,
            decorative=spec.decorative,
            data_fallback=_chart_data_fallback(spec),
        )
