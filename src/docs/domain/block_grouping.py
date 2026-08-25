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

from collections import Counter
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
# Only a FALLBACK: see `PARAGRAPH_SPACING_RATIO` for the signal that actually
# works.
PARAGRAPH_GAP_RATIO = 1.6

# A new paragraph starts when the baseline step exceeds the page's own line
# spacing by this much. Baseline-to-baseline is the signal a typesetter
# actually used; the ink gap above only approximates it, and approximated
# wrongly. Measured on a real page: lines within a paragraph stepped 16.0pt
# and paragraphs were separated by 32.0pt -- exactly double -- yet the ink-gap
# rule computed 19.2 against a 20.5 threshold and merged eight short
# paragraphs into three. The page then had huge blank gaps and a paragraph
# running past the right margin.
#
# 1.7 sits in the real gap between the two: ordinary leading runs 1.2-1.45
# times the type size, and a paragraph break is 2 or more. 1.5 was inside the
# leading range and split a body paragraph mid-sentence, because its italic
# runs sit ~3pt lower than the roman ones on the same visual line, which
# stretches the measured step.
PARAGRAPH_SPACING_RATIO = 1.7

# Below this many measured steps there is no reliable modal spacing, so the
# ink-gap fallback is safer than a number derived from two lines.
MIN_STEPS_FOR_SPACING = 3

# Two stacked lines belong to one block only if they actually sit above each
# other. Without this a chart title and a far-left axis label merge.
MIN_HORIZONTAL_OVERLAP = 0.1

# A change of font size between stacked lines is a block boundary: a heading
# and the paragraph under it are not one paragraph. Without this, a 24pt
# heading absorbed the 11pt body text below it, and since a block draws at its
# LARGEST size the whole paragraph was rendered at heading size -- a page of
# giant overlapping text. Measured on a real book, and the visual collapse
# floor caught it at 0.39.
MAX_FONT_SIZE_RATIO = 1.25

# Style suffixes a font name appends to its base family. Stripping them is
# what separates "a different typeface" from "the same typeface, emphasised".
_STYLE_SUFFIXES = (
    "bolditalic", "boldoblique", "semibold", "italic", "oblique", "bold",
    "black", "heavy", "light", "medium", "regular", "roman", "book", "it",
)


def base_family(name: str) -> str:
    """`Baskerville-Italic` -> `baskerville`; `Courier` -> `courier`.

    A block splits on a change of TYPEFACE, never on emphasis. The two are
    indistinguishable in the raw name -- `Baskerville` and
    `Baskerville-Italic` are different strings for the same face -- and
    treating them as different families cut every sentence apart at each
    italicised word. Measured on a real book: `"We know we ought to talk to
    customers"` became three blocks, `"We know we"`, `"ought"` and the rest,
    which destroyed the sentence for the translator AND made the fragments
    overlap when redrawn. 48 blocks were invading their neighbours.
    """
    stem = name.lower().replace(" ", "")
    for separator in ("-", ",", "_"):
        stem = stem.split(separator)[0]
    for suffix in _STYLE_SUFFIXES:
        if stem.endswith(suffix) and len(stem) > len(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem


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
    # Style travels with the run for the same reason the family does: the
    # source distinguishes speech from inner thought with italics, and a
    # translation that flattens both into roman loses information the author
    # put there on purpose.
    bold: bool = False
    italic: bool = False

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
        """The first named family in the block, or "" when none is known.

        Safe only because a family CHANGE ends a block: without that rule this
        rendered a whole dialogue line in the monospace face of its "Son:"
        label, swallowing the serif speech beside it.
        """
        return next((run.font_family for run in self.runs if run.font_family), "")

    @property
    def bold(self) -> bool:
        return self.runs[0].bold

    @property
    def italic(self) -> bool:
        return self.runs[0].italic

    @property
    def style(self) -> str:
        """What makes a block typographically homogeneous: the FAMILY only.

        Deliberately NOT bold/italic. A family change is a change of ROLE -- a
        monospace `Son:` label beside serif dialogue -- and those are separate
        units. An italic run inside a serif paragraph is EMPHASIS inside one
        sentence, and that sentence has to reach the translator whole.

        Measured: splitting on italic too took a 120-page book from 1191
        blocks to 1596 and the blocks that no longer fit their box from 21 to
        218, because each fragment inherits only its own narrow bbox. The
        emphasis is lost either way -- after translation there is no mapping
        from translated words back to the italic source run -- so paying for
        it in fit and in translation quality buys nothing.
        """
        return base_family(self.font_family)

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
    def advance_ratio(self) -> float | None:
        """Mean glyph advance as a fraction of type size, measured EXACTLY.

        Every run carries both its own text and the width that text actually
        occupied, so this needs no assumption about how full each line was.
        Deriving it from the block's bounding box instead required guessing
        that every line ran the full column width, and the last line of a
        paragraph never does -- that overestimated the advance, wrapped the
        translation early, and left every paragraph visibly narrower than the
        one it replaced.

        `None` when there is nothing to measure; the caller then falls back to
        a constant.
        """
        characters = sum(len(run.text) for run in self.runs)
        total = sum(run.width for run in self.runs)
        size = self.font_size
        if characters == 0 or total <= 0 or size <= 0:
            return None
        return total / (characters * size)

    @property
    def first_line_x(self) -> float:
        """Where the block's FIRST line actually started.

        Not the same as `x`, which is the leftmost edge of the whole block. A
        hanging indent -- a dialogue label with the speech beginning to its
        right and continuation lines tucked under the speech -- makes those
        two different, and redrawing the first line at `x` slid it left into
        the label, printing "Son" and the opening quote on top of each other.
        """
        top = max(run.top for run in self.runs)
        first = [run for run in self.runs if abs(run.top - top) <= _line_tolerance(run, run)]
        return min(run.x for run in first) if first else self.x

    @property
    def line_count(self) -> int:
        """How many baselines the ORIGINAL text occupied.

        The fitter needs this because `height` is the height of the INK, not
        of the lines: a single line of 14pt text measures about 9-13pt tall,
        so comparing it against a 16.5pt line height marks every single-line
        block as overflowing -- while it holds the very text the box was drawn
        around.
        """
        baselines: list[float] = []
        for run in self.runs:
            if not any(abs(run.y - y) <= _line_tolerance(run, run) for y in baselines):
                baselines.append(run.y)
        return max(len(baselines), 1)

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
        style_changed = base_family(previous.font_family) != base_family(run.font_family)
        size_changed = max(previous.font_size, run.font_size) > MAX_FONT_SIZE_RATIO * min(
            previous.font_size, run.font_size
        ) if min(previous.font_size, run.font_size) > 0 else False
        if style_changed or size_changed or run.x - previous.right > COLUMN_GAP_RATIO * max(previous.font_size, run.font_size):
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


def modal_line_spacing(lines: list[list[TextRun]]) -> float | None:
    """The page's own within-paragraph baseline step, or `None` if unknowable.

    The SMALLEST step that repeats, not the most common one. A page alternates
    between line steps and paragraph steps, so on a page of two-line
    paragraphs the two counts tie and `most_common` picks whichever came
    first -- measured: it returned the 32pt PARAGRAPH step as the line
    spacing, which merged the entire page into a single block. Within-
    paragraph spacing is by construction the smaller of the two.

    "Repeats" filters out one-off steps: a heading's gap or a stray
    superscript would otherwise become the whole page's line spacing.

    Rounded to whole points before counting: real baselines carry sub-point
    jitter, and without rounding every step looks unique and nothing repeats.
    """
    steps: list[int] = []
    for upper, lower in pairwise(lines):
        step = round(max(run.y for run in upper) - max(run.y for run in lower))
        if step > 0:
            steps.append(step)
    if len(steps) < MIN_STEPS_FOR_SPACING:
        return None
    counts = Counter(steps)
    repeated = [step for step, times in counts.items() if times >= 2]
    return float(min(repeated)) if repeated else float(min(steps))


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
        page_lines = _lines([r for r in runs if r.page == page])
        spacing = modal_line_spacing(page_lines)
        open_blocks: list[TextBlock] = []
        previous_line: list[TextRun] | None = None
        for line in page_lines:
            line_segments = _segments(line)
            attached: list[TextBlock] = []
            for segment in line_segments:
                target = _continuable(open_blocks, segment, previous_line, spacing)
                if target is None:
                    target = TextBlock()
                    blocks.append(target)
                target.runs.extend(segment)
                attached.append(target)
            open_blocks = attached
            previous_line = line
    return blocks


def _continuable(
    open_blocks: list[TextBlock],
    segment: list[TextRun],
    previous_line: list[TextRun] | None,
    spacing: float | None = None,
) -> TextBlock | None:
    """The open block this segment continues, or `None` to start a new one."""
    if previous_line is None:
        return None
    if spacing is not None:
        step = max(run.y for run in previous_line) - max(run.y for run in segment)
        # Take the LARGER of the page's measured spacing and the local type
        # size. One page-wide number is fragile when a page mixes headings
        # with body text -- measured, a page whose body stepped 16pt reported
        # a page-global 13pt because its running head is smaller, and the
        # tighter threshold then split a paragraph mid-sentence. The local
        # size cannot be fooled that way, and the measured spacing catches
        # generous leading the size alone would miss.
        local = max(run.font_size for run in (*previous_line, *segment))
        if step > max(spacing, local) * PARAGRAPH_SPACING_RATIO:
            return None
    else:
        tallest = max(run.height for run in (*previous_line, *segment))
        gap = min(run.y for run in previous_line) - max(run.top for run in segment)
        if gap > tallest * PARAGRAPH_GAP_RATIO:
            return None
    segment_size = max(run.font_size for run in segment)
    segment_style = base_family(segment[0].font_family)
    for block in open_blocks:
        if not _overlaps(block, segment):
            continue
        if block.style != segment_style:
            # A different face or weight means a different role. Merging them
            # renders the block in whichever style came first.
            continue
        larger = max(block.font_size, segment_size)
        smaller = min(block.font_size, segment_size)
        if smaller > 0 and larger / smaller > MAX_FONT_SIZE_RATIO:
            # Different type size means different role. Joining them makes the
            # block draw at the LARGER size, which renders body text at
            # heading size and buries the page.
            continue
        return block
    return None
