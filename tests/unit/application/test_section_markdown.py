# tests/unit/application/test_section_markdown.py
"""`strip_frontmatter_to_temp` (design.md ADR-5, tasks.md S4 4.3-4.4): new
coverage for the shared frontmatter-strip/numbering pass every
`DocumentRendererPort` implementation reuses. `bound_figures`, when
provided, must forward unchanged into `number_and_resolve`; omitted, output
stays byte-identical to today (regression guard)."""
from __future__ import annotations

from docs.application.section_markdown import strip_frontmatter_to_temp
from docs.domain.figure_binding import BoundFigure


def test_bound_figures_omitted_is_byte_identical_to_current_behavior(tmp_path):
    section = tmp_path / "001-resumen.md"
    section.write_text("[[figure:organigrama]] Organigrama del equipo.\n", encoding="utf-8")

    stripped = strip_frontmatter_to_temp([section])

    assert stripped[0].read_text(encoding="utf-8") == "Figura 1. Organigrama del equipo.\n"


def test_bound_figures_none_is_byte_identical_to_omitted(tmp_path):
    section = tmp_path / "001-resumen.md"
    section.write_text("[[figure:organigrama]] Organigrama del equipo.\n", encoding="utf-8")

    stripped = strip_frontmatter_to_temp([section], bound_figures=None)

    assert stripped[0].read_text(encoding="utf-8") == "Figura 1. Organigrama del equipo.\n"


def test_bound_figures_is_forwarded_to_number_and_resolve(tmp_path):
    section = tmp_path / "001-resumen.md"
    section.write_text("[[figure:organigrama]] Organigrama del equipo.\n", encoding="utf-8")
    bound = {
        "organigrama": BoundFigure(
            label="organigrama",
            catalog_id="fig-abc12345",
            path="/abs/path/fig-abc12345.png",
            width_px=300,
            height_px=200,
            caption="Organigrama del equipo",
        )
    }

    stripped = strip_frontmatter_to_temp([section], bound_figures=bound)

    text = stripped[0].read_text(encoding="utf-8")
    assert (
        text
        == "![Figura 1. Organigrama del equipo](/abs/path/fig-abc12345.png){width=3.12in}"
        " Organigrama del equipo.\n"
    )


def test_unbound_label_still_resolves_to_text_only_caption_when_bound_figures_given(tmp_path):
    section = tmp_path / "001-resumen.md"
    section.write_text("[[figure:no-vinculada]] Otra figura.\n", encoding="utf-8")
    bound = {
        "organigrama": BoundFigure(
            label="organigrama",
            catalog_id="fig-abc12345",
            path="/abs/path/fig-abc12345.png",
            width_px=300,
            height_px=200,
            caption="Organigrama del equipo",
        )
    }

    stripped = strip_frontmatter_to_temp([section], bound_figures=bound)

    assert stripped[0].read_text(encoding="utf-8") == "Figura 1. Otra figura.\n"
