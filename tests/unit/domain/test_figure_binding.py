# tests/unit/domain/test_figure_binding.py
"""Pure sizing + markdown embedding for a resolved figure binding
(design.md ADR-5). `BoundFigure` is the application-resolved join of
`figure-catalog.json` + `figure-bindings.json`; these functions turn it into
the pandoc-embeddable markdown that `number_and_resolve` (cross_reference.py)
substitutes for a bound `[[figure:label]]` marker."""
from __future__ import annotations

from docs.domain.figure_binding import (
    BoundFigure,
    figure_image_markdown,
    figure_width_attr,
)


def test_width_attr_is_empty_for_none_width():
    assert figure_width_attr(None) == ""


def test_width_attr_derives_inches_from_assumed_dpi_below_clamp():
    # 192px / 96 DPI = 2.0in -- well under the 6.0in content-width clamp.
    assert figure_width_attr(192) == "{width=2.0in}"


def test_width_attr_clamps_to_max_content_width():
    # 1200px / 96 DPI = 12.5in -- clamped to MAX_CONTENT_WIDTH_IN=6.0.
    assert figure_width_attr(1200) == "{width=6.0in}"


def _bound_figure(*, width_px: int | None = 192, caption: str = "") -> BoundFigure:
    return BoundFigure(
        label="organigrama",
        catalog_id="fig-abcd1234",
        path="/abs/assets/figures/fig-abcd1234.png",
        width_px=width_px,
        height_px=100,
        caption=caption,
    )


def test_image_markdown_embeds_path_and_caption():
    fig = _bound_figure(caption="Organigrama del equipo.")

    markdown = figure_image_markdown(1, fig)

    assert markdown == (
        "![Figura 1. Organigrama del equipo.]"
        "(/abs/assets/figures/fig-abcd1234.png){width=2.0in}"
    )


def test_image_markdown_empty_caption_rstrips_trailing_space():
    fig = _bound_figure(caption="")

    markdown = figure_image_markdown(2, fig)

    assert markdown == "![Figura 2.](/abs/assets/figures/fig-abcd1234.png){width=2.0in}"
