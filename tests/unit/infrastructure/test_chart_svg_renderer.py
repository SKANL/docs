# tests/unit/infrastructure/test_chart_svg_renderer.py
"""`VisualRendererPort` implementation for `type = "chart"`: matplotlib Agg
SVG backend, declarative spec only (design.md Decision "chart spec is
DECLARATIVE data, never executed code"; Threat Matrix "Documentation-like /
execution boundary" — `source` is parsed with `json.loads` ONLY, never
`eval`/`exec`/`subprocess`)."""
from __future__ import annotations

import hashlib
import json
from unittest import mock

import pytest

from docs.domain.ports.visual_renderer_port import VisualSpec
from docs.domain.svg_normalize import normalize_svg
from docs.infrastructure.visuals.chart_svg_renderer import ChartSvgRenderer

_BAR_SOURCE = json.dumps(
    {
        "kind": "bar",
        "labels": ["Q1", "Q2", "Q3"],
        "series": [{"label": "Revenue", "values": [10, 20, 15]}],
    }
)


def test_python_looking_source_text_renders_as_inert_data():
    # A series label that LOOKS like Python/shell code must be treated as
    # literal display text -- never eval'd, exec'd, or shelled out.
    malicious_label = "__import__('os').system('id')"
    source = json.dumps(
        {
            "kind": "bar",
            "labels": ["Q1", "Q2"],
            "series": [{"label": malicious_label, "values": [1, 2]}],
        }
    )
    spec = VisualSpec(label="fig", type="chart", source=source)

    with (
        mock.patch("builtins.eval") as mock_eval,
        mock.patch("builtins.exec") as mock_exec,
        mock.patch("subprocess.run") as mock_run,
    ):
        svg = ChartSvgRenderer().render(spec)

    mock_eval.assert_not_called()
    mock_exec.assert_not_called()
    mock_run.assert_not_called()
    assert malicious_label in svg


def test_render_bar_chart_produces_svg_text():
    spec = VisualSpec(label="fig", type="chart", source=_BAR_SOURCE)

    svg = ChartSvgRenderer().render(spec)

    assert "<svg" in svg


def test_render_plus_normalize_svg_is_byte_identical_across_two_runs():
    spec = VisualSpec(label="fig", type="chart", source=_BAR_SOURCE)

    first = normalize_svg(ChartSvgRenderer().render(spec))
    second = normalize_svg(ChartSvgRenderer().render(spec))

    assert hashlib.sha256(first.encode()).hexdigest() == hashlib.sha256(second.encode()).hexdigest()


def test_unknown_chart_kind_raises_documented_error():
    source = json.dumps({"kind": "scatter3d", "labels": ["a"], "series": [{"values": [1]}]})
    spec = VisualSpec(label="fig", type="chart", source=source)

    with pytest.raises(ValueError, match="scatter3d"):
        ChartSvgRenderer().render(spec)


def test_missing_required_field_raises_documented_error():
    source = json.dumps({"kind": "bar", "series": [{"values": [1]}]})
    spec = VisualSpec(label="fig", type="chart", source=source)

    with pytest.raises(ValueError, match="labels"):
        ChartSvgRenderer().render(spec)
