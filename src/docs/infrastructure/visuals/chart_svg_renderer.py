# src/docs/infrastructure/visuals/chart_svg_renderer.py
from __future__ import annotations

import io
import json

import matplotlib

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

from docs.domain.ports.visual_renderer_port import VisualSpec

# Renderer-side determinism knobs (design.md "Renderer-side determinism
# knobs"): fixed literal salt for internal clip-path/gradient ids +
# `fonttype=none` so glyphs are emitted as literal `<text>` content rather
# than hashed font-glyph paths -- `svg_normalize.normalize_svg` handles the
# rest (id rewriting, comment/metadata stripping).
_SVG_HASHSALT = "docs-chart-svg-renderer"
_SUPPORTED_KINDS = {"bar", "line", "pie"}


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
        data = _parse_source(spec.source)
        kind = data.get("kind")
        if kind not in _SUPPORTED_KINDS:
            raise ValueError(
                f"Unsupported chart kind {kind!r}; expected one of {sorted(_SUPPORTED_KINDS)}."
            )
        labels = data.get("labels")
        if not isinstance(labels, list) or not labels:
            raise ValueError("Chart spec is missing required non-empty field 'labels'.")
        series = data.get("series")
        if not isinstance(series, list) or not series:
            raise ValueError("Chart spec is missing required non-empty field 'series'.")

        rc = {
            "svg.hashsalt": _SVG_HASHSALT,
            "svg.fonttype": "none",
            "font.family": "DejaVu Sans",
        }
        with matplotlib.rc_context(rc):
            fig, ax = plt.subplots()
            try:
                _RENDER_BY_KIND[kind](ax, labels, series)
                buf = io.BytesIO()
                fig.savefig(buf, format="svg", metadata={"Date": None})
            finally:
                plt.close(fig)
        return buf.getvalue().decode("utf-8")


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
    return entry["values"]


def _render_bar(ax, labels: list, series: list) -> None:
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


def _render_line(ax, labels: list, series: list) -> None:
    handles, names = [], []
    for entry in series:
        (line,) = ax.plot([str(label) for label in labels], _series_values(entry))
        handles.append(line)
        names.append(str(entry.get("label", "")))
    ax.legend(handles, names)


def _render_pie(ax, labels: list, series: list) -> None:
    ax.pie(_series_values(series[0]), labels=[str(label) for label in labels])


_RENDER_BY_KIND = {"bar": _render_bar, "line": _render_line, "pie": _render_pie}
