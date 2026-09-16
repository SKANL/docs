from __future__ import annotations

import json

from docs.domain.ports.visual_renderer_port import VisualSpec
from docs.domain.svg_normalize import ensure_accessibility_metadata
from docs.infrastructure.visuals.chart_svg_renderer import ChartSvgRenderer


def test_visual_spec_derives_stable_accessible_metadata():
    spec = VisualSpec(label="revenue", type="chart", source="{}", caption="Revenue")

    assert spec.accessible_name == "Revenue"
    assert spec.accessible_description == "Generated visual: Revenue."


def test_svg_accessibility_metadata_is_escaped_and_deterministic():
    first = ensure_accessibility_metadata("<svg><rect/></svg>", "A & B", "A < B")
    second = ensure_accessibility_metadata("<svg><rect/></svg>", "A & B", "A < B")

    assert first == second
    assert '<title id="visual-title">A &amp; B</title>' in first
    assert '<desc id="visual-desc">A &lt; B</desc>' in first


def test_svg_accessibility_metadata_links_svg_to_title_and_description():
    svg = ensure_accessibility_metadata("<svg><rect/></svg>", "Revenue", "Revenue by quarter.")

    assert '<svg aria-labelledby="visual-title visual-desc">' in svg
    assert '<title id="visual-title">Revenue</title>' in svg
    assert '<desc id="visual-desc">Revenue by quarter.</desc>' in svg


def test_chart_renderer_emits_title_and_description():
    source = json.dumps({"kind": "bar", "labels": ["Q1"], "series": [{"label": "Revenue", "values": [1]}]})
    svg = ChartSvgRenderer().render(VisualSpec(label="revenue", type="chart", source=source, caption="Revenue"))

    assert '<title id="visual-title">Revenue</title>' in svg
    assert '<desc id="visual-desc">Generated visual: Revenue.</desc>' in svg
