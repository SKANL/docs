from __future__ import annotations

import json

import pytest

from docs.domain.ports.visual_renderer_port import VisualSpec
from docs.domain.svg_normalize import ensure_accessibility_metadata, normalize_svg
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


def test_decorative_svg_is_hidden_from_assistive_technology():
    svg = ensure_accessibility_metadata(
        '<svg role="img" aria-labelledby="old" aria-hidden="false"><title>old</title><rect/></svg>',
        "",
        "",
        decorative=True,
    )

    assert 'role="presentation"' in svg
    assert 'aria-hidden="true"' in svg
    assert "aria-labelledby" not in svg


def test_svg_metadata_handles_namespaces_and_existing_semantics():
    svg = ensure_accessibility_metadata(
        '<svg xmlns="http://www.w3.org/2000/svg"><title>old</title><desc>old</desc><rect/></svg>',
        "Name & more",
        "Description",
    )

    assert svg.count("visual-title") == 2
    assert svg.count("visual-desc") == 2
    assert "Name &amp; more" in svg


def test_chart_renderer_emits_title_and_description():
    source = json.dumps({"kind": "bar", "labels": ["Q1"], "series": [{"label": "Revenue", "values": [1]}]})
    svg = ChartSvgRenderer().render(VisualSpec(label="revenue", type="chart", source=source, caption="Revenue"))

    assert '<title id="visual-title">Revenue</title>' in svg
    assert '<desc id="visual-desc">Generated visual: Revenue.</desc>' in svg


def test_svg_normalization_rewrites_style_text_references_without_changing_xml_text():
    svg = (
        '<svg><style>/* keep #old in a comment */ #old { fill: url(#old); '
        'content: "#old"; }</style><g id="old"/></svg>'
    )

    normalized = normalize_svg(svg)

    assert '<style>/* keep #old in a comment */ #n0 { fill: url(#n0); content: "#old"; }</style>' in normalized
    assert '<g id="n0" />' in normalized


def test_svg_parser_rejects_entity_declarations_before_expansion():
    hostile_svg = '<!DOCTYPE svg [<!ENTITY payload "expanded">]><svg><text>&payload;</text></svg>'

    with pytest.raises(ValueError, match="Unsafe SVG XML"):
        normalize_svg(hostile_svg)
