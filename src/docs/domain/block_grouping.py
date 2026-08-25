# src/docs/domain/block_grouping.py
"""Geometric grouping of PDF text runs into translation blocks.

A PDF stores text as positioned runs with no notion of a sentence, or even of
a word: a single visual line arrives as several runs, and a ligature can split
one word in two. Translating one run at a time asks the model to translate
"fi" and "nance team" separately, which reads exactly as badly as it sounds.
Runs are therefore grouped into BLOCKS -- a block is both the unit of
translation and the bounding box the translated text must fit back into.

Every threshold here is proportional to font size rather than absolute,
because all three defects this module has already produced came from fixed
constants meeting real documents:

- A fixed 2.0pt baseline tolerance split ONE line of 11pt text whose runs sat
  at y=681.12, 680.96 and 678.82 into two lines, and the block then read
  "fi nance team Prepared by the" -- the words in the wrong ORDER.
- With no horizontal-gap rule, seven chart axis labels sharing a baseline 32pt
  apart became one block and were redrawn left-aligned in the corner.
- With no horizontal-overlap requirement, a chart title at x=189 merged with
  an axis label at x=39 purely because their baselines were close.

Pure geometry. No I/O, no imports from other layers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

# Baseline jitter within one visual line, as a fraction of font size. Measured
# need: 2.3pt of drift on 11pt text, i.e. 0.21 -- 0.35 leaves headroom without
# reaching the ~1.18 line spacing that separates genuine lines.
LINE_TOLERANCE_RATIO = 0.35

# Horizontal gap that ends a block, as a fraction of font size. An ordinary
# inter-word space is ~0.25; chart axis labels sat ~2.9 apart.
COLUMN_GAP_RATIO = 1.2

# Below this gap the runs are touching, so joining them with a space would
# insert one that is not in the document -- this is the ligature case, where
# "fl" and "at" must rejoin as "flat", not "fl at".
ADJACENT_GAP_RATIO = 0.2

# Vertical gap that ends a block, as a fraction of the taller line's height.
PARAGRAPH_GAP_RATIO = 1.6

# Two stacked lines belong to one block only if they actually sit above each
# other. Without this a chart title and a far-left axis label merge.
MIN_HORIZONTAL_OVERLAP = 0.1


@dataclass(frozen=True)
class TextRun:
    """One positioned text object as read from the PDF.

    `x`/`y` are the lower-left corner in PDF user space, where y grows UPWARD.
    """

    text: str
    x: float
    y: float
    width: float
    height: float
    page: int
    font_size: float
    # Serif vs sans is one of the most VISIBLE differences on a page, so the
    # family travels with the run: the writer maps it onto a standard font,
    # and a whole document silently turning from Times into Helvetica would
    # fail the visual gate for a reason nobody could see. Defaulted so
    # pure-geometry callers need not supply it.
    font_family: str = ""

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y + self.height


@dataclass
class TextBlock:
    """Runs that read as one unit and share one bounding box."""

    runs: list[TextRun] = field(default_factory=list)

    @property
    def page(self) -> int:
        return self.runs[0].page

    @property
    def text(self) -> str:
        """The block's text, joined in reading order.

        Runs that are touching are joined WITHOUT a space: a ligature split
        arrives as "fl" + "at" and must read "flat". Inserting a space there
        corrupts the word before the translator ever sees it.

        Whitespace is collapsed at the end: runs often carry their own
        trailing space ("Prepared by the "), which would otherwise combine
        with the separator into a double space and change the block's
        identity -- and therefore its translation-memory key -- for a reason
        no reader can see.
        """
        parts: list[str] = []
        previous: TextRun | None = None
        for run in self.runs:
            if previous is not None:
                same_line = abs(run.y - previous.y) <= _line_tolerance(previous, run)
                gap = run.x - previous.right
                touching = same_line and gap < ADJACENT_GAP_RATIO * run.font_size
                parts.append("" if touching else " ")
            parts.append(run.text)
            previous = run
        return " ".join("".join(parts).split())

    @property
    def font_size(self) -> float:
        # The largest run wins: shrinking a heading to body size is a visible
        # regression, and the fitter can still shrink from here if it must.
        return max(run.font_size for run in self.runs)

    @property
    def font_family(self) -> str:
        """The first named family in the block, or "" when none is known."""
        return next((run.font_family for run in self.runs if run.font_family), "")

    @property
    def x(self) -> float:
        return min(run.x for run in self.runs)

    @property
    def right(self) -> float:
        return max(run.right for run in self.runs)

    @property
    def bottom(self) -> float:
        return min(run.y for run in self.runs)

    @property
    def top(self) -> float:
        return max(run.top for run in self.runs)

    @property
    def width(self) -> float:
        return self.right - self.x

    @property
    def height(self) -> float:
        return self.top - self.bottom


def _line_tolerance(a: TextRun, b: TextRun) -> float:
    return max(a.font_size, b.font_size) * LINE_TOLERANCE_RATIO


def _lines(runs: list[TextRun]) -> list[list[TextRun]]:
    """Cluster runs sharing a baseline, each line ordered left to right.

    A run joins the line whose baseline is nearest and within tolerance --
    nearest, not first-within-tolerance, so a line whose runs drift steadily
    does not split at an arbitrary point.
    """
    lines: list[list[TextRun]] = []
    for run in sorted(runs, key=lambda r: (-r.y, r.x)):
        best: list[TextRun] | None = None
        best_distance = float("inf")
        for line in lines:
            distance = abs(line[0].y - run.y)
            if distance <= _line_tolerance(line[0], run) and distance < best_distance:
                best, best_distance = line, distance
        if best is None:
            lines.append([run])
        else:
            best.append(run)
    for line in lines:
        line.sort(key=lambda r: r.x)
    return lines


def _segments(line: list[TextRun]) -> list[list[TextRun]]:
    """Split one baseline wherever a horizontal gap is too wide to be a space.

    This is what keeps seven chart axis labels from becoming one block that
    gets redrawn left-aligned in the corner.
    """
    segments: list[list[TextRun]] = [[line[0]]]
    for previous, run in pairwise(line):
        if run.x - previous.right > COLUMN_GAP_RATIO * max(previous.font_size, run.font_size):
            segments.append([run])
        else:
            segments[-1].append(run)
    return segments


def _overlaps(block: TextBlock, segment: list[TextRun]) -> bool:
    left = max(block.x, min(run.x for run in segment))
    right = min(block.right, max(run.right for run in segment))
    narrower = min(block.width, max(run.right for run in segment) - min(run.x for run in segment))
    if narrower <= 0:
        return left <= right
    return (right - left) / narrower >= MIN_HORIZONTAL_OVERLAP


def group_runs_into_blocks(runs: list[TextRun]) -> list[TextBlock]:
    """Group `runs` into reading blocks, page by page, top to bottom.

    A block grows downward while the next segment sits close enough
    vertically AND overlaps horizontally. Anything else starts a new block.

    # ponytail: single-column assumption. Two text columns side by side are
    # separated correctly by the horizontal-gap rule, but a paragraph
    # continuing from the bottom of one column to the top of the next is
    # still two blocks rather than one sentence. `pdf-inspector` reports
    # `pages_with_columns`, and `TranslateService` reports those pages as
    # unverified instead of presenting a guess. Replacing this with
    # pdf-inspector reading order is the upgrade path.
    """
    blocks: list[TextBlock] = []
    for page in sorted({run.page for run in runs}):
        open_blocks: list[TextBlock] = []
        previous_line: list[TextRun] | None = None
        for line in _lines([r for r in runs if r.page == page]):
            line_segments = _segments(line)
            attached: list[TextBlock] = []
            for segment in line_segments:
                target = _continuable(open_blocks, segment, previous_line)
                if target is None:
                    target = TextBlock()
                    blocks.append(target)
                target.runs.extend(segment)
                attached.append(target)
            open_blocks = attached
            previous_line = line
    return blocks


def _continuable(
    open_blocks: list[TextBlock], segment: list[TextRun], previous_line: list[TextRun] | None
) -> TextBlock | None:
    """The open block this segment continues, or `None` to start a new one."""
    if previous_line is None:
        return None
    tallest = max(run.height for run in (*previous_line, *segment))
    gap = min(run.y for run in previous_line) - max(run.top for run in segment)
    if gap > tallest * PARAGRAPH_GAP_RATIO:
        return None
    for block in open_blocks:
        if _overlaps(block, segment):
            return block
    return None
