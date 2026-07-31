# src/docs/domain/cross_reference.py
from __future__ import annotations

import re

from docs.domain.figure_binding import BoundFigure, figure_image_markdown

# ponytail: same `[[...]]` marker family as `[[TOC]]` (section_rendering.py:34)
# and `[[figure:fig-<sha8>]]` (figure_catalog.py:9) -- no new syntax family.
# Labels are symbolic slugs (author-chosen, not catalog sha8 ids); the
# numbering pass below is independent of the figure catalog.
_FIGURE_LABEL_RE = re.compile(r"\[\[figure:([\w-]+)\]\]")
_TABLE_LABEL_RE = re.compile(r"\[\[table:([\w-]+)\]\]")
_REF_RE = re.compile(r"\[\[ref:([\w-]+)\]\]")


def number_and_resolve(
    ordered_sections: list[tuple[str, str]],
    bound_figures: dict[str, BoundFigure] | None = None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Pure numbering + cross-reference pass (design.md item H, ADR-H).

    `ordered_sections` is `(section_id, text)` already in document order
    (the same `sorted(sections, key=order)` order `build` computes). Walks
    it once to assign `Figura 1..N` / `Tabla 1..M` to each distinct
    `[[figure:label]]`/`[[table:label]]` in first document-order,
    then-in-text-order appearance -- a total order, so re-running on the
    same input (or a reordered one) is fully deterministic. Rewrites each
    label marker to its `Figura N.`/`Tabla M.` caption prefix and each
    `[[ref:label]]` to `Ver Figura N`/`Ver Tabla M`. An unresolvable ref
    becomes `Ver Figura ?` plus a warning naming the label -- never a
    silent guess. Text with no markers
    (e.g. a section that already hand-writes `Figura N.`) passes through
    unchanged -- backward compatible with documents authored before this
    feature existed.

    `bound_figures` (design.md ADR-4/ADR-5) is the application-resolved
    `label -> BoundFigure` map. When a `[[figure:label]]` marker's label is
    a key in `bound_figures`, it is replaced by pandoc-embeddable image
    markdown (`figure_image_markdown`) instead of the plain `Figura N.`
    text -- embedding never changes numbering, only the marker's
    replacement. Default `None` (or a label absent from the map) reproduces
    the unchanged text-only path byte-for-byte -- every existing caller
    that omits this argument is unaffected.
    """
    figure_numbers: dict[str, int] = {}
    table_numbers: dict[str, int] = {}
    for _section_id, text in ordered_sections:
        for label in _FIGURE_LABEL_RE.findall(text):
            figure_numbers.setdefault(label, len(figure_numbers) + 1)
        for label in _TABLE_LABEL_RE.findall(text):
            table_numbers.setdefault(label, len(table_numbers) + 1)

    warnings: list[str] = []

    def _figure_sub(match: re.Match[str]) -> str:
        label = match.group(1)
        number = figure_numbers[label]
        if bound_figures is not None and label in bound_figures:
            return figure_image_markdown(number, bound_figures[label])
        return f"Figura {number}."

    def _rewrite(section_id: str, text: str) -> str:
        text = _FIGURE_LABEL_RE.sub(_figure_sub, text)
        text = _TABLE_LABEL_RE.sub(lambda m: f"Tabla {table_numbers[m.group(1)]}.", text)

        def _ref_sub(match: re.Match[str]) -> str:
            label = match.group(1)
            if label in figure_numbers:
                return f"Ver Figura {figure_numbers[label]}"
            if label in table_numbers:
                return f"Ver Tabla {table_numbers[label]}"
            warnings.append(
                f"{section_id}: [[ref:{label}]] no resuelve a ninguna figura/tabla declarada."
            )
            return "Ver Figura ?"

        return _REF_RE.sub(_ref_sub, text)

    rewritten = [(section_id, _rewrite(section_id, text)) for section_id, text in ordered_sections]
    return rewritten, warnings
