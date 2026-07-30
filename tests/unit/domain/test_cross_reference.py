# tests/unit/domain/test_cross_reference.py
"""Build-time figure/table numbering + cross-ref resolution (design.md item
H, ADR-H). `number_and_resolve` is pure: same ordered sections always yield
the same numbers/text -- no timestamps, no randomness. Authors write
symbolic `[[figure:<label>]]`/`[[table:<label>]]` markers (same `[[...]]`
family as `[[TOC]]`, figure_catalog.py's `[[figure:fig-<sha8>]]`) instead of
hand-assigning `Figura N`/`Tabla N`."""
from __future__ import annotations

from docs.domain.cross_reference import number_and_resolve


def test_assigns_figures_in_document_order_then_in_text_order():
    sections = [
        ("intro", "[[figure:foo]] texto [[figure:bar]] mas"),
        ("cierre", "[[figure:baz]]"),
    ]

    rewritten, warnings = number_and_resolve(sections)

    body = dict(rewritten)
    assert body["intro"] == "Figura 1. texto Figura 2. mas"
    assert body["cierre"] == "Figura 3."
    assert warnings == []


def test_numbers_tables_independently_of_figures():
    sections = [("a", "[[figure:foo]] [[table:bar]]")]

    rewritten, warnings = number_and_resolve(sections)

    assert rewritten[0][1] == "Figura 1. Tabla 1."
    assert warnings == []


def test_ref_resolves_to_assigned_figure_number():
    sections = [
        ("a", "[[figure:organigrama]] Organigrama del equipo."),
        ("b", "Consulte [[ref:organigrama]] para detalles."),
    ]

    rewritten, warnings = number_and_resolve(sections)

    body = dict(rewritten)
    assert body["a"] == "Figura 1. Organigrama del equipo."
    assert body["b"] == "Consulte Ver Figura 1 para detalles."
    assert warnings == []


def test_ref_resolves_to_assigned_table_number():
    sections = [
        ("a", "[[table:precios]] Precios del proyecto."),
        ("b", "Detalle en [[ref:precios]]."),
    ]

    rewritten, warnings = number_and_resolve(sections)

    body = dict(rewritten)
    assert body["a"] == "Tabla 1. Precios del proyecto."
    assert body["b"] == "Detalle en Ver Tabla 1."
    assert warnings == []


def test_unresolvable_ref_becomes_placeholder_and_reports_warning():
    sections = [("a", "Consulte [[ref:no-existe]].")]

    rewritten, warnings = number_and_resolve(sections)

    assert rewritten[0][1] == "Consulte Ver Figura ?."
    assert len(warnings) == 1
    assert "no-existe" in warnings[0]


def test_leaves_hardcoded_captions_untouched_backward_compatible():
    # Sections that already hand-write `Figura N.` (no markers) must build
    # unchanged -- the current generated document does exactly this.
    sections = [("a", "Figura 1. Ya está numerada a mano.")]

    rewritten, warnings = number_and_resolve(sections)

    assert rewritten == sections
    assert warnings == []


def test_reordering_sections_renumbers_to_match_new_document_order():
    original = [("a", "[[figure:foo]]"), ("b", "[[figure:bar]]")]
    rewritten_original, _ = number_and_resolve(original)
    assert dict(rewritten_original) == {"a": "Figura 1.", "b": "Figura 2."}

    reordered = [("b", "[[figure:bar]]"), ("a", "[[figure:foo]]")]
    rewritten_reordered, _ = number_and_resolve(reordered)
    assert dict(rewritten_reordered) == {"b": "Figura 1.", "a": "Figura 2."}


def test_deterministic_across_independent_runs():
    sections = [("a", "[[figure:foo]] [[ref:foo]]"), ("b", "[[figure:bar]] [[ref:bar]]")]

    first = number_and_resolve(list(sections))
    second = number_and_resolve(list(sections))

    assert first == second
