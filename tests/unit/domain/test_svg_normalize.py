# tests/unit/domain/test_svg_normalize.py
"""normalize_svg (design.md "normalize_svg lives in domain") -- the
determinism spike that makes two renderer-produced SVGs of the same diagram
byte-identical despite tool-generated ids/comments/metadata timestamps that
vary run-to-run. Pure regex-based pass over ids only (see the module's
`# ponytail:` note), never a full XML parse."""
from __future__ import annotations

import hashlib

from docs.domain.svg_normalize import normalize_svg


def test_strips_xml_comments():
    text = "<svg><!-- Created with matplotlib v1.2.3 --><rect/></svg>"
    normalized = normalize_svg(text)
    assert "<!--" not in normalized
    assert "matplotlib" not in normalized


def test_strips_metadata_block():
    text = (
        "<svg><metadata><rdf:RDF><dc:date>2024-01-01</dc:date>"
        "</rdf:RDF></metadata><rect/></svg>"
    )
    normalized = normalize_svg(text)
    assert "<metadata>" not in normalized
    assert "2024-01-01" not in normalized


def test_rewrites_id_definitions_in_first_appearance_order():
    text = '<svg><clipPath id="zzz9"/><clipPath id="aaa1"/></svg>'
    normalized = normalize_svg(text)
    assert 'id="n0"' in normalized
    assert 'id="n1"' in normalized
    assert "zzz9" not in normalized
    assert "aaa1" not in normalized
    assert normalized.index('id="n0"') < normalized.index('id="n1"')


def test_rewrites_all_reference_forms():
    text = (
        "<svg>"
        '<clipPath id="p1a2b3c4"/>'
        '<g clip-path="url(#p1a2b3c4)">'
        '<use href="p1a2b3c4"/>'
        '<use href="#p1a2b3c4"/>'
        '<use xlink:href="#p1a2b3c4"/>'
        '<text aria-labelledby="p1a2b3c4">t</text>'
        "</g></svg>"
    )
    normalized = normalize_svg(text)
    assert "p1a2b3c4" not in normalized
    # 1 definition + 5 reference forms, all mapped to the same n0 token
    assert normalized.count("n0") == 6


def test_rewrites_aria_describedby_mermaid_accdescr():
    # mermaid's accDescr accessibility helper emits aria-describedby="<run-
    # varying id>" plus a matching <desc id="..."> -- the reference has no
    # leading '#', so without an explicit rule the <desc> definition gets
    # renamed while the aria-describedby reference keeps the raw run-varying
    # token, leaking it and breaking byte-determinism (review CRITICAL).
    text = '<svg aria-describedby="chart-desc-9f3"><desc id="chart-desc-9f3">d</desc></svg>'
    normalized = normalize_svg(text)
    assert "chart-desc-9f3" not in normalized  # both def and ref rewritten, no leak
    assert normalized.count("n0") == 2  # 1 definition + 1 aria-describedby reference


def test_longest_id_first_avoids_substring_collision():
    # id "a" must not corrupt a reference to "abc" (design.md: replace
    # longest-id-first).
    text = '<svg><style>#abc{fill:red} #a{fill:blue}</style><g id="abc"/><g id="a"/></svg>'
    normalized = normalize_svg(text)
    assert "abc" not in normalized
    assert "#n0{fill:red}" in normalized
    assert "#n1{fill:blue}" in normalized


def test_byte_identical_across_two_calls_on_same_input():
    text = '<svg><clipPath id="p1"/></svg>'
    assert normalize_svg(text) == normalize_svg(text)


def test_structurally_identical_svgs_differing_only_in_ids_comments_metadata_are_byte_identical():
    svg_a = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!-- Created with matplotlib v3.9.0, 2024-01-01T00:00:00 -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">\n'
        " <metadata>\n"
        "  <rdf:RDF><dc:date>2024-01-01T00:00:00</dc:date></rdf:RDF>\n"
        " </metadata>\n"
        " <defs>\n"
        '  <clipPath id="p1a2b3c4">\n'
        '   <rect x="0" y="0" width="100" height="100"/>\n'
        "  </clipPath>\n"
        " </defs>\n"
        ' <g clip-path="url(#p1a2b3c4)">\n'
        '  <use xlink:href="#p1a2b3c4"/>\n'
        " </g>\n"
        "</svg>\n"
    )
    svg_b = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!-- Created with matplotlib v3.9.1, 2026-08-03T12:34:56 -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">\n'
        " <metadata>\n"
        "  <rdf:RDF><dc:date>2026-08-03T12:34:56</dc:date></rdf:RDF>\n"
        " </metadata>\n"
        " <defs>\n"
        '  <clipPath id="q9z8y7x6">\n'
        '   <rect x="0" y="0" width="100" height="100"/>\n'
        "  </clipPath>\n"
        " </defs>\n"
        ' <g clip-path="url(#q9z8y7x6)">\n'
        '  <use xlink:href="#q9z8y7x6"/>\n'
        " </g>\n"
        "</svg>\n"
    )

    normalized_a = normalize_svg(svg_a)
    normalized_b = normalize_svg(svg_b)

    assert normalized_a == normalized_b
    assert (
        hashlib.sha256(normalized_a.encode()).hexdigest()
        == hashlib.sha256(normalized_b.encode()).hexdigest()
    )
