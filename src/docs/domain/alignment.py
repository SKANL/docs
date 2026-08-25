# src/docs/domain/alignment.py
"""Infer how a block was aligned, so the translation is drawn the same way.

A PDF stores no alignment. It stores where each run was placed, and the
alignment is a property of the ORIGINAL text's width -- which the translation
changes. Redrawing every block at its left edge is therefore wrong for exactly
the blocks a reader notices first: centred titles, running heads, and
right-aligned page numbers all slide left as soon as the text length changes.

The signal is on the page itself. Body text shares a left and a right margin,
and those two most common edges define the column. A block that sits inside
both margins but whose midpoint matches the column's midpoint was centred; one
whose right edge meets the column's right margin while its left edge does not
meet the left was right-aligned. Everything else is left-aligned, which is both
the common case and the safe default.

Pure geometry. No I/O, no imports from other layers.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

# How far an edge may sit from a margin and still count as touching it. A
# fraction of the column width, so it scales with the page rather than
# assuming points.
EDGE_TOLERANCE = 0.02

# How far a block's midpoint may sit from the column's midpoint and still
# count as centred. Looser than the edge tolerance because centring is
# computed from two edges, so it accumulates both their errors.
CENTRE_TOLERANCE = 0.04

# A block must be meaningfully narrower than the column before its alignment
# is even a question: a full-width paragraph is left-aligned by definition,
# and its midpoint trivially matches the column's.
MAX_CENTRED_WIDTH = 0.9


class Alignment(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"
    """Flush on BOTH margins. Detected from the source's own line ends rather
    than inferred from the column, because a justified block states it
    unambiguously: every line but the last stops at the same x."""


@dataclass(frozen=True)
class Column:
    """The text column of one page, as the page itself reveals it."""

    left: float
    right: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def centre(self) -> float:
        return (self.left + self.right) / 2


def detect_column(lefts: Sequence[float], rights: Sequence[float]) -> Column | None:
    """The dominant left and right edges of a page, or `None` if there is no
    dominant pair -- a page of scattered fragments has no column, and guessing
    one would misalign every block on it."""
    if not lefts or not rights:
        return None
    left = Counter(round(value) for value in lefts).most_common(1)[0][0]
    right = Counter(round(value) for value in rights).most_common(1)[0][0]
    if right <= left:
        return None
    return Column(float(left), float(right))


def detect_alignment(
    block_left: float, block_right: float, column: Column | None
) -> Alignment:
    """Classify one block against its page's column.

    Left is the default and the fallback: it is the common case, and being
    wrong about it moves text the least.
    """
    if column is None or column.width <= 0:
        return Alignment.LEFT

    block_width = block_right - block_left
    if block_width >= column.width * MAX_CENTRED_WIDTH:
        return Alignment.LEFT

    edge = column.width * EDGE_TOLERANCE
    touches_left = abs(block_left - column.left) <= edge
    touches_right = abs(block_right - column.right) <= edge
    if touches_left:
        # An edge on the left margin is left-aligned even when it happens to
        # look centred, because that is where its next line would start.
        return Alignment.LEFT

    midpoint = (block_left + block_right) / 2
    if abs(midpoint - column.centre) <= column.width * CENTRE_TOLERANCE:
        return Alignment.CENTER
    if touches_right:
        return Alignment.RIGHT
    return Alignment.LEFT
