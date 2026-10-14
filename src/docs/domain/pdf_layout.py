"""Pure PDF text-layout and post-write geometry helpers.

Nothing here touches PDFium: the adapter measures objects and hands plain
numbers, strings and `BlockReplacement`s to these functions.
"""

from __future__ import annotations

from dataclasses import dataclass

from docs.domain.alignment import Alignment
from docs.domain.ports.pdf_text_edit_port import BlockReplacement

# PDFium bounds are floating-point measurements. Differences up to half a
# point are treated as equivalent at every post-save geometry boundary.
POST_WRITE_TOLERANCE_POINTS = 0.5

Bounds = tuple[float, float, float, float]

# Subset tags are exactly six uppercase letters followed by "+".
_SUBSET_TAG_LENGTH = 6

# Base-14 covers four styles per family, so italic and bold survive the
# substitution instead of being flattened. The source book distinguishes
# spoken words from inner thought purely with italics; dropping that loses
# meaning the author put there deliberately.
BASE14 = {
    b"Times-Roman": (b"Times-Roman", b"Times-Bold", b"Times-Italic", b"Times-BoldItalic"),
    b"Helvetica": (b"Helvetica", b"Helvetica-Bold", b"Helvetica-Oblique", b"Helvetica-BoldOblique"),
    b"Courier": (b"Courier", b"Courier-Bold", b"Courier-Oblique", b"Courier-BoldOblique"),
}


@dataclass(frozen=True)
class ObjectSnapshot:
    object_index: int
    text: str | None
    bounds: Bounds


def styled(font: bytes, bold: bool, italic: bool) -> bytes:
    regular, bold_face, italic_face, both = BASE14[font]
    if bold and italic:
        return both
    if bold:
        return bold_face
    if italic:
        return italic_face
    return regular


def line_start(replacement: BlockReplacement, line_number: int) -> float:
    """The left edge available to one line, before alignment moves it.

    Line 0 keeps the start the original had; a hanging indent means that is
    NOT the block's leftmost edge.
    """
    if line_number == 0 and replacement.first_line_x:
        return replacement.first_line_x
    return replacement.x


def line_x(replacement: BlockReplacement, line: str, line_number: int) -> float:
    """Where one laid-out line starts, honouring the block's alignment.

    Measured with the fitter's OWN calibration rather than a fresh guess: two
    different width estimates for the same line would place it somewhere the
    wrapper never intended.
    """
    left = line_start(replacement, line_number)
    # A justified line reaching here is the paragraph's LAST one, which a
    # justified paragraph never stretches -- it sits flush left. Without this
    # it fell through to the right-aligned branch and every paragraph ended
    # with a line pushed against the right margin.
    if (
        replacement.alignment in (Alignment.LEFT, Alignment.JUSTIFY)
        or replacement.right <= left
    ):
        return left
    slack = (replacement.right - left) - replacement.fitted.line_width(line)
    if slack <= 0:
        return left
    if replacement.alignment is Alignment.CENTER:
        return left + slack / 2
    return left + slack


def strip_subset_tag(name: str) -> str:
    """`GGKEDP+DejaVuSans` -> `DejaVuSans`; anything else is returned as-is."""
    prefix, plus, rest = name.partition("+")
    if plus and len(prefix) == _SUBSET_TAG_LENGTH and prefix.isalpha() and prefix.isupper():
        return rest
    return name


def drop_unmapped(text: str) -> str:
    """Remove control characters left by glyphs the font never mapped.

    A PDF whose font encoding is incomplete hands back raw CID codes instead
    of Unicode -- exactly what `pdf-inspector` means by `has_encoding_issues`,
    which this document reported and which was ignored once already. Measured
    on a 120-page book: 17 U+0002 and 3 U+0001, each a hyphen or ligature at
    a line break, reaching the reader as visible garbage.

    Dropping them is right for the common case rather than merely tidy: the
    character is a LINE-BREAK hyphen, so "mis" + "interpreted" rejoins as
    "misinterpreted", which is the word the author wrote. Keeping a code we
    cannot decode only guarantees it reaches the reader as noise.
    """
    return "".join(ch for ch in text if ch.isprintable() or ch.isspace())


def outside(inner: Bounds, outer: Bounds) -> bool:
    tolerance = POST_WRITE_TOLERANCE_POINTS
    return (
        inner[0] < outer[0] - tolerance
        or inner[1] < outer[1] - tolerance
        or inner[2] > outer[2] + tolerance
        or inner[3] > outer[3] + tolerance
    )


def overlaps(first: Bounds, second: Bounds) -> bool:
    tolerance = POST_WRITE_TOLERANCE_POINTS
    return (
        min(first[2], second[2]) - max(first[0], second[0]) > tolerance
        and min(first[3], second[3]) - max(first[1], second[1]) > tolerance
    )


def union(bounds: list[Bounds]) -> Bounds:
    return (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )


def missing_expected_lines(
    expected: tuple[ObjectSnapshot, ...], actual: list[ObjectSnapshot] | tuple[ObjectSnapshot, ...]
) -> tuple[ObjectSnapshot, ...]:
    remaining = list(actual)
    missing: list[ObjectSnapshot] = []
    for item in expected:
        for index, candidate in enumerate(remaining):
            if candidate.text == item.text:
                remaining.pop(index)
                break
        else:
            missing.append(item)
    return tuple(missing)


def permitted_bounds(
    replacement: BlockReplacement, expected_lines: tuple[ObjectSnapshot, ...]
) -> Bounds:
    starts = [replacement.x]
    if replacement.first_line_x:
        starts.append(replacement.first_line_x)
    source_bottom = min((run.y for run in replacement.remove), default=replacement.top)
    baseline = replacement.baseline or (replacement.top - replacement.fitted.font_size)
    first_line_bottom = (
        expected_lines[0].bounds[1] if expected_lines else source_bottom
    )
    ink_descent = min(0.0, first_line_bottom - baseline)
    return min(starts), source_bottom + ink_descent, replacement.right, replacement.top


def match_key(text: str, left: float, bottom: float) -> tuple[str, float, float]:
    """Objects are re-read from a freshly opened document, so pointers differ
    between the read and the write. Text plus rounded position is the join."""
    return text, round(left, 1), round(bottom, 1)
