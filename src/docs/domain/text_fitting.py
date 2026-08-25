# src/docs/domain/text_fitting.py
"""Fit translated text back into the bounding box it came from.

Translation changes length -- EN->ES runs about 20-25% longer -- so the
translated string does not fit the box the original occupied. The strategy is
wrap first, shrink second, and REPORT third: a block that cannot be fitted
even at `min_scale` is marked `overflowed` so the pipeline can count it. A
silently clipped block is the failure mode this flag exists to prevent.

Pure geometry. No I/O, no imports from other layers.
"""
from __future__ import annotations

from dataclasses import dataclass

from docs.domain.block_grouping import TextBlock
from docs.domain.fonts import advance_ratio_for

# Mean glyph advance as a fraction of font size, for Helvetica-like faces.
# ponytail: a constant, not real font metrics. PDFium exposes
# `FPDFFont_GetGlyphWidth` for exact advances; swap this for a width callback
# injected by the adapter when a measured document shows the estimate drifting
# far enough to misjudge a fit. Until then this keeps the domain layer pure
# and free of any PDF dependency.
_MEAN_ADVANCE_RATIO = 0.5

_LINE_SPACING = 1.18
_SHRINK_STEP = 0.5


@dataclass(frozen=True)
class FittedText:
    """The laid-out result, and whether it had to give up."""

    lines: list[str]
    font_size: float
    overflowed: bool
    advance_ratio: float = _MEAN_ADVANCE_RATIO
    """The calibration used to measure these lines. The writer needs the SAME
    number to place a centred or right-aligned line, or it would measure the
    text differently from the code that wrapped it."""


    def line_width(self, line: str) -> float:
        return len(line) * self.font_size * self.advance_ratio


# A block whose measured ratio falls outside this is not measuring what we
# think -- a one-character block, a bbox that includes leading art -- so the
# default is safer than the measurement.
_PLAUSIBLE_RATIO = (0.25, 0.9)


def measured_advance_ratio(
    text: str, width: float, font_size: float, line_count: int = 1
) -> float:
    """Calibrate the width estimate against the block's OWN original text.

    The constant below is a guess for a Helvetica-like face, and a guess is
    what produced 215 blocks reported as not fitting their box while still
    holding their untranslated English -- which is impossible by definition,
    since the original text is exactly what the box was drawn around.

    We already know the truth for every block: its source text and the width
    that text actually occupied. Dividing one by the other gives this
    document's real ratio, per block, for free. Short blocks are where the
    constant's error dominates, and they are also where this is most exact.

    `line_count` is not optional in spirit: `width` is the width of ONE line,
    so dividing it by the characters of ALL the lines halves the ratio of a
    two-line block. The estimator then believes every glyph is half as wide,
    packs twice as much onto each line, and the text runs off the right
    margin -- which is exactly what it did on a real page.
    """
    characters = len(text.strip()) / max(line_count, 1)
    if characters <= 0 or font_size <= 0 or width <= 0:
        return _MEAN_ADVANCE_RATIO
    ratio = width / (characters * font_size)
    low, high = _PLAUSIBLE_RATIO
    return ratio if low <= ratio <= high else _MEAN_ADVANCE_RATIO


def _estimated_width(text: str, font_size: float, ratio: float) -> float:
    return len(text) * font_size * ratio


def _wrap(
    text: str,
    width: float,
    font_size: float,
    ratio: float,
    first_width: float | None = None,
) -> tuple[list[str], bool]:
    """Greedy word wrap. Returns the lines and whether any single word was
    wider than the box -- a word that cannot be broken cannot be fitted, and
    shrinking further will not save it past the floor.

    `first_width` is the room available on LINE 0, which a hanging indent
    makes smaller than the block's width: dialogue whose speech begins to the
    right of its label has its continuation lines tucked back underneath.
    Wrapping line 0 to the full width overran the right margin by 94-101px on
    every dialogue page of a real book -- an inch of text off the column,
    invisible to any check that measured with the same estimator that laid it
    out.
    """
    lines: list[str] = []
    current = ""
    too_wide = False
    for word in text.split():
        room = first_width if not lines and first_width is not None else width
        if _estimated_width(word, font_size, ratio) > room:
            too_wide = True
        candidate = f"{current} {word}".strip()
        if current and _estimated_width(candidate, font_size, ratio) > room:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines, too_wide


def fit_text_to_block(
    text: str,
    block: TextBlock,
    min_scale: float = 0.6,
    max_height: float | None = None,
    max_width: float | None = None,
) -> FittedText:
    """Lay `text` out inside `block`, shrinking only as far as `min_scale`.

    `min_scale` is a floor rather than a target: text shrunk past roughly 60%
    of its neighbours stops reading as the same document, so overflowing
    visibly and being counted beats becoming illegible quietly.
    """
    if not text.strip():
        return FittedText(lines=[], font_size=block.font_size, overflowed=False)

    # The SUBSTITUTE font's advance, not the source's. The source font never
    # reaches the page -- its glyphs are not there -- so laying out with its
    # metrics wraps for a font nobody will see, and the real one then runs off
    # the margin. Measured from PDFium, per face and weight.
    ratio = advance_ratio_for(block.font_family)
    base = block.font_size
    floor = base * min_scale
    # The room available is what the ORIGINAL text occupied, measured in
    # LINES rather than in ink height. `block.height` is the height of the
    # glyphs, not of the lines they sit on, so using it directly reported
    # every single-line block as overflowing while it still held its own
    # untranslated text.
    # The room that actually exists, not just the block's own extent. A
    # heading whose translation needs a second line must SHRINK rather than
    # grow into the paragraph beneath it -- the caller measures the gap and
    # passes it here.
    own_extent = max(block.height, block.line_count * base * _LINE_SPACING)
    available = own_extent if max_height is None else max(max_height, base)
    # A block's own right edge is where its ORIGINAL text happened to stop,
    # not where the page allows text to reach. For a left-aligned heading that
    # difference is the whole problem: "Passing the mom test" ended at x=400,
    # so the longer Spanish wrapped to a second line and dropped onto the
    # dialogue below, while 120pt of empty column sat unused beside it. The
    # caller passes the column's right edge; the block's own is the fallback.
    right = max_width if max_width is not None and max_width > block.x else block.right
    width = right - block.x
    first_width = max(right - block.first_line_x, 0.0) or width
    size = base
    while True:
        lines, word_too_wide = _wrap(text, width, size, ratio, first_width)
        needed = len(lines) * size * _LINE_SPACING
        if not word_too_wide and needed <= available:
            return FittedText(lines=lines, font_size=size, overflowed=False, advance_ratio=ratio)
        if size <= floor:
            return FittedText(lines=lines, font_size=floor, overflowed=True, advance_ratio=ratio)
        size = max(floor, size - _SHRINK_STEP)
