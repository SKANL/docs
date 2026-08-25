# src/docs/domain/collision.py
"""Detect translated blocks that would land on top of another block.

Translation changes how many lines a block needs, so a block can grow
downwards into the one below it. That is the single most damaging thing this
capability can do to a page, and it is invisible from the output line unless
someone measures it: the document is written, every stage reports success, and
only rendering the page shows two paragraphs printed over each other.

So it is measured here and counted, in the same spirit as every other
compromise this capability reports. Same lesson as `qa-docx`: a stage that
degrades where only a file can tell you reads as a clean success.

Pure geometry. No I/O, no imports from other layers.
"""
from __future__ import annotations

from collections.abc import Iterable

from docs.domain.block_grouping import TextBlock
from docs.domain.text_fitting import FittedText

# Baselines closer than this belong to the same visual LINE, not to stacked
# lines. Without it a dialogue label and the speech beside it -- whose boxes
# legitimately overlap, and whose baselines differ by a fraction of a point --
# read as 90 collisions on a book that had 3.
SAME_LINE_TOLERANCE = 4.0

# Fraction of the type size allowed to hang below the last baseline before it
# counts as touching the block underneath: descenders are not a collision.
DESCENDER_SHARE = 0.25

_FALLBACK_LEADING = 1.18


def drawn_bottom(block: TextBlock, fitted: FittedText) -> float:
    """The lowest point the laid-out text will occupy."""
    leading = block.line_spacing or fitted.font_size * _FALLBACK_LEADING
    extra = max(len(fitted.lines) - 1, 0)
    return block.baseline - extra * leading - fitted.font_size * DESCENDER_SHARE


# Breathing room kept between a grown block and the one beneath it, as a
# fraction of type size. Without it a block may end exactly on its
# neighbour's baseline, which reads as touching.
CLEARANCE_SHARE = 0.35


def vertical_room(block: TextBlock, page_blocks: Iterable[TextBlock]) -> float | None:
    """How far `block` may grow downwards before it reaches its neighbour.

    Handing this to the fitter is what turns a collision into a slightly
    smaller heading. Without it the fitter only knows the block's own extent,
    so a title whose translation needs a second line simply grows into the
    text below -- measured on a real book, a chapter heading landed on the
    first line of dialogue under it.

    `None` when nothing sits below it in the same column, which means the
    block may use its own extent as before.
    """
    below = [
        other
        for other in page_blocks
        if other is not block
        and other.page == block.page
        and _overlaps_horizontally(block, other)
        and block.baseline - other.baseline >= SAME_LINE_TOLERANCE
    ]
    if not below:
        return None
    nearest = max(other.baseline for other in below)
    clearance = block.font_size * CLEARANCE_SHARE
    return max(block.baseline - nearest - clearance, 0.0)


def _overlaps_horizontally(a: TextBlock, b: TextBlock) -> bool:
    return not (a.right < b.x or b.right < a.x)


def collides(placements: Iterable[tuple[TextBlock, FittedText]]) -> list[TextBlock]:
    """The blocks whose laid-out text reaches into a block below them.

    Returns the offending blocks, so a caller can count them and name their
    pages rather than reporting a bare number nobody can act on.
    """
    laid_out = list(placements)
    offenders: list[TextBlock] = []
    for index, (block, fitted) in enumerate(laid_out):
        if not fitted.lines:
            continue
        bottom = drawn_bottom(block, fitted)
        for other, _ in laid_out[index + 1 :]:
            if other.page != block.page:
                continue
            if not _overlaps_horizontally(block, other):
                continue
            if block.baseline - other.baseline < SAME_LINE_TOLERANCE:
                continue
            if bottom < other.baseline + 1:
                offenders.append(block)
                break
    return offenders
