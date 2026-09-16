# src/docs/infrastructure/visuals/chart_svg_renderer.py
from __future__ import annotations

import io
import json
import math
from numbers import Real

import matplotlib

# First-party import kept above the matplotlib block so it is not flagged
# E402 by the eager-backend-setup code below (which must run before any
# pyplot use); VisualSpec has no matplotlib dependency.
from docs.domain.ports.visual_renderer_port import VisualSpec
from docs.domain.svg_normalize import ensure_accessibility_metadata

matplotlib.use("Agg")

import matplotlib.pyplot as plt

# Force EAGER backend + SVG-canvas module load here, at import time --
# `matplotlib.use()` alone only sets rcParams; both the figure-manager
# backend AND the per-format (`savefig(format="svg")`) canvas are otherwise
# deferred to first use, and that lazy `importlib.import_module` path
# internally relies on `exec()`-based pyplot-bridging machinery that would
# otherwise collide with a caller's `unittest.mock.patch("builtins.exec")`
# around `render()` (Threat Matrix RED test) -- eagerly resolving both here
# keeps that patch scoped to OUR code, not matplotlib's own unrelated
# internals.
plt.switch_backend("Agg")
_warmup_fig = plt.figure()
_warmup_fig.savefig(io.BytesIO(), format="svg")
plt.close(_warmup_fig)

# Renderer-side determinism knobs (design.md "Renderer-side determinism
# knobs"): fixed literal salt for internal clip-path/gradient ids +
# `fonttype=none` so glyphs are emitted as literal `<text>` content rather
# than hashed font-glyph paths -- `svg_normalize.normalize_svg` handles the
# rest (id rewriting, comment/metadata stripping).
_SVG_HASHSALT = "docs-chart-svg-renderer"
_SUPPORTED_KINDS = {"bar", "line", "pie"}
_MAX_SOURCE_LENGTH = 1_000_000
_MAX_LABELS = 1_000
_MAX_SERIES = 100
_MAX_VALUES = 100_000
_MAX_OUTPUT_LENGTH = 4_000_000


class ChartSvgRenderer:
    """`VisualRendererPort` implementation for `type = "chart"`: renders a
    DECLARATIVE spec (design.md Decision "chart spec is DECLARATIVE data,
    never executed code") via matplotlib's Agg backend to SVG text.
    `spec.source` is parsed with `json.loads` ONLY -- never `eval`/`exec` --
    so an agent-authored spec can never become executable code (Threat
    Matrix: "Documentation-like / execution boundary"). Raises `ValueError`
    on malformed/unknown-kind specs so the generate-visuals stage (Slice 5)
    can WARN+skip."""

    type = "chart"

    def render(self, spec: VisualSpec) -> str:
        if len(spec.source) > _MAX_SOURCE_LENGTH:
            raise ValueError(f"Chart spec source exceeds {_MAX_SOURCE_LENGTH} characters.")
        data = _parse_source(spec.source)
        kind = data.get("kind")
        if kind not in _SUPPORTED_KINDS:
            raise ValueError(f"Unsupported chart kind {kind!r}; expected one of {sorted(_SUPPORTED_KINDS)}.")
        labels = data.get("labels")
        if not isinstance(labels, list) or not labels:
            raise ValueError("Chart spec is missing required non-empty field 'labels'.")
        series = data.get("series")
        if not isinstance(series, list) or not series:
            raise ValueError("Chart spec is missing required non-empty field 'series'.")

        # Inlined, not bound to a name first: matplotlib types `rc_context`
        # against a Literal union of every known rcParam key, and only the
        # call site gives the checker that expected type to infer against
        # (a `rc = {...}` variable widens to `dict[str, str]` before it
        # reaches the parameter). These three keys are what make the SVG
        # deterministic -- fixed hash salt, no font hashing, pinned family.
        with matplotlib.rc_context(
            {
                "svg.hashsalt": _SVG_HASHSALT,
                "svg.fonttype": "none",
                "font.family": "DejaVu Sans",
            }
        ):
            fig, ax = plt.subplots()
            try:
                _validate_chart_data(labels, series)
                _RENDER_BY_KIND[kind](ax, labels, series, spec.unit)
                buf = io.BytesIO()
                fig.savefig(buf, format="svg", metadata={"Date": None})
            finally:
                plt.close(fig)
        raw_svg = buf.getvalue()
        if len(raw_svg) > _MAX_OUTPUT_LENGTH:
            raise ValueError(f"Chart SVG output exceeds {_MAX_OUTPUT_LENGTH} bytes.")
        return ensure_accessibility_metadata(
            raw_svg.decode("utf-8"),
            spec.accessible_name,
            spec.accessible_description,
            decorative=spec.decorative,
        )


def _parse_source(source: str) -> dict:
    try:
        data = json.loads(source)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Chart spec 'source' is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Chart spec 'source' must be a JSON object.")
    return data


def _series_values(entry: object) -> list:
    if not isinstance(entry, dict) or "values" not in entry:
        raise ValueError("Each chart series entry must be an object with a 'values' field.")
    values = entry["values"]
    if not isinstance(values, list):
        raise ValueError("Each chart series 'values' field must be a list of numeric values.")
    return values


def _validate_chart_data(labels: list, series: list) -> None:
    if len(labels) > _MAX_LABELS:
        raise ValueError(f"Chart spec has too many labels; maximum is {_MAX_LABELS}.")
    if len(series) > _MAX_SERIES:
        raise ValueError(f"Chart spec has too many series; maximum is {_MAX_SERIES}.")
    total_values = 0
    for entry in series:
        values = _series_values(entry)
        total_values += len(values)
        if total_values > _MAX_VALUES:
            raise ValueError(f"Chart spec has too many values; maximum is {_MAX_VALUES}.")
        if len(values) != len(labels):
            raise ValueError("Each chart series must have the same number of values as labels.")
        if any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) for value in values):
            raise ValueError("Chart series values must be finite numeric values.")


def _render_bar(ax, labels: list, series: list, unit: str = "") -> None:
    x = list(range(len(labels)))
    width = 0.8 / max(len(series), 1)
    handles, names = [], []
    for i, entry in enumerate(series):
        offsets = [xi + i * width - 0.4 + width / 2 for xi in x]
        handles.append(ax.bar(offsets, _series_values(entry), width=width))
        names.append(str(entry.get("label", "")))
    ax.set_xticks(x)
    ax.set_xticklabels([str(label) for label in labels])
    # A series `label` is agent-authored display text (Threat Matrix: it must
    # render as literal text, never be interpreted). Passed explicitly to
    # `legend(handles, names)` rather than via each artist's `label=` kwarg:
    # matplotlib's *automatic* legend collection silently drops any label
    # starting with `_` (its "private artist" convention) -- an
    # agent-authored label that happens to start with `__` (e.g. dunder-
    # looking text) would otherwise vanish from the rendered chart.
    ax.legend(handles, names)
    if unit.strip():
        ax.set_ylabel(unit.strip())


def _render_line(ax, labels: list, series: list, unit: str = "") -> None:
    handles, names = [], []
    for entry in series:
        (line,) = ax.plot([str(label) for label in labels], _series_values(entry))
        handles.append(line)
        names.append(str(entry.get("label", "")))
    ax.legend(handles, names)
    if unit.strip():
        ax.set_ylabel(unit.strip())


def _render_pie(ax, labels: list, series: list, unit: str = "") -> None:
    ax.pie(_series_values(series[0]), labels=[str(label) for label in labels])


_RENDER_BY_KIND = {"bar": _render_bar, "line": _render_line, "pie": _render_pie}
