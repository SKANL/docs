# src/docs/infrastructure/pdf/pypdfium2_text_edit_adapter.py
"""In-place PDF text editing via the raw PDFium API.

Three PDFium behaviours make this file more delicate than it looks, all three
MEASURED against a real document rather than inferred:

1. Mutating page objects while a textpage is open SILENTLY DESTROYS unrelated
   text objects -- a 3-object page came back as 2, with nothing raised. The
   read phase and the write phase are therefore strictly separated by
   `FPDFText_ClosePage`, and that ordering is not an optimisation to tidy up.
2. Every save stamps a RANDOM trailer `/ID`, so identical input yields
   different bytes. The save therefore ends in `normalize_pdf_id`.
3. `FPDFFont_GetFamilyName` is present, returns success, and yields an EMPTY
   string for embedded subset fonts. `FPDFFont_GetBaseFontName` is the call
   that works. "Present" is not "usable".

`FPDFPage_RemoveObject` transfers ownership to the caller, so every removal is
paired with `FPDFPageObj_Destroy`.
"""
from __future__ import annotations

import ctypes
import math
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from docs.domain.alignment import Alignment
from docs.domain.block_grouping import DOMINANT_STYLE_SHARE, TextRun
from docs.domain.fonts import needs_embedded_font, substitute_font
from docs.domain.pdf_id import normalize_pdf_id
from docs.domain.ports.font_source_port import FontSourcePort
from docs.domain.ports.pdf_text_edit_port import BlockReplacement, WriteReport

_LINE_SPACING = 1.18

# Subset tags are exactly six uppercase letters followed by "+".
_SUBSET_TAG_LENGTH = 6

# Original fonts are embedded as SUBSETS holding only the glyphs the document
# already used, so a target-language glyph that never appeared is simply not
# there. Map the family onto a base-14 standard font, which always carries
# full Latin coverage, and count the substitution.
#
# DO NOT "optimise" this by keeping the original font. `FPDFText_SetText` on
# an EXISTING text object succeeds and preserves its font, which looks like
# the obvious way to keep perfect typography. It was measured on a real book:
#
#     wrote:    "PRUEBA de acentos: canción, año, ¿qué?"
#     rendered: "PRUEA de centos[]cncin[]o[]u[]"
#
# Not merely the accents -- the lowercase "a" is gone too, because that
# running head's subset carries only the glyphs of "The Mom Test by @robfitz
# 10" and nothing else. And it fails SILENTLY: the text layer read back the
# correct Spanish, so only rendering the page reveals the damage.
#
# Substitution is not a shortcut here. It is the only option that produces a
# readable document.
# ponytail: base-14 only, so non-Latin targets (Cyrillic, CJK, Arabic) are out
# of reach. The upgrade path is `FPDFText_LoadFont` with a bundled Noto face,
# which is a licensing and file-size decision rather than a code one.
#
# The family NAME is the signal, not the descriptor flags. PDFium exposes
# `FPDFFont_GetFlags`, and on a real book those flags are simply wrong:
# `Courier` reported `FixedPitch=False` and `Baskerville` reported
# `Serif=False`. Both false. The call succeeds and the answer is useless.
#
# The list has to be broad enough to cover a real document's body face. It
# started with four names, and `Baskerville` -- 2631 runs, the entire body of
# a 120-page book -- fell through to Helvetica, silently turning a serif book
# sans-serif. An unrecognised family is now COUNTED and reported rather than
# quietly guessed at.
# Family classification and the measured advances now live in `domain/fonts.py`,
# so the layout code and the writer cannot disagree about which face is used.

# Base-14 covers four styles per family, so italic and bold survive the
# substitution instead of being flattened. The source book distinguishes
# spoken words from inner thought purely with italics; dropping that loses
# meaning the author put there deliberately.
_BASE14 = {
    b"Times-Roman": (b"Times-Roman", b"Times-Bold", b"Times-Italic", b"Times-BoldItalic"),
    b"Helvetica": (b"Helvetica", b"Helvetica-Bold", b"Helvetica-Oblique", b"Helvetica-BoldOblique"),
    b"Courier": (b"Courier", b"Courier-Bold", b"Courier-Oblique", b"Courier-BoldOblique"),
}

def _styled(font: bytes, bold: bool, italic: bool) -> bytes:
    regular, bold_face, italic_face, both = _BASE14[font]
    if bold and italic:
        return both
    if bold:
        return bold_face
    if italic:
        return italic_face
    return regular


def _line_start(replacement: BlockReplacement, line_number: int) -> float:
    """The left edge available to one line, before alignment moves it.

    Line 0 keeps the start the original had; a hanging indent means that is
    NOT the block's leftmost edge.
    """
    if line_number == 0 and replacement.first_line_x:
        return replacement.first_line_x
    return replacement.x


def _line_x(replacement: BlockReplacement, line: str, line_number: int) -> float:
    """Where one laid-out line starts, honouring the block's alignment.

    Measured with the fitter's OWN calibration rather than a fresh guess: two
    different width estimates for the same line would place it somewhere the
    wrapper never intended.
    """
    left = _line_start(replacement, line_number)
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


# How far a drawn line may be re-shrunk to fit its column before we accept
# the overrun. Deeper than the fitter's own floor because this is the last
# line of defence: past here the text leaves the page.
# Sine of the smallest angle counted as a rotation. Sub-degree skews occur in
# ordinary documents and are not worth refusing to translate over.
_ROTATION_TOLERANCE = 0.02

_MIN_FIT_SCALE = 0.5

# Most a justified line may be stretched horizontally. Beyond this the glyphs
# read as visibly distorted, so the line is left ragged instead: a slightly
# short line is a smaller lie than a squashed typeface.
MAX_JUSTIFY_STRETCH = 1.12


# Two passes are enough: the first correction is proportional, the second
# absorbs the rounding. A third buys nothing measurable.
_FIT_PASSES = 2


def _place_within(
    document: Any,
    font: Any,
    line: str,
    size: float,
    left: float,
    limit: float,
    justify: bool = False,
) -> tuple[Any, float]:
    """Build and position one line so its ink ends at or before `limit`.

    The fitter estimates widths; PDFium knows them. But knowing the object's
    WIDTH is not enough -- a text object carries a side bearing, so ink does
    not begin exactly at the placement point. Measuring the width alone left a
    uniform 11-13px overrun on most pages, which is the tell-tale shape of a
    systematic offset rather than an estimation error.

    So measure the object where it will actually sit: transform first, then
    read its bounds in PAGE coordinates and compare the right edge against the
    column. That is the same question a reader asks.
    """
    def build(at_size: float, stretch: float = 1.0) -> Any:
        obj = pdfium_c.FPDFPageObj_CreateTextObj(document.raw, font, at_size)
        pdfium_c.FPDFText_SetText(obj, _widestring(line))
        # Scale about the origin, THEN translate: the object is created at
        # x=0, so this leaves its left edge exactly at `left`.
        pdfium_c.FPDFPageObj_Transform(obj, stretch, 0, 0, 1, left, 0)
        return obj

    obj = build(size)
    if limit <= left:
        return obj, size

    floor = size * _MIN_FIT_SCALE
    for _ in range(_FIT_PASSES):
        _, _, right, _ = _object_bounds(obj)
        overshoot = right - limit
        if overshoot <= 0:
            break
        drawn = right - left
        if drawn <= 0:
            break
        scaled = max(size * ((limit - left) / drawn), floor)
        if scaled >= size:
            break
        size = scaled
        pdfium_c.FPDFPageObj_Destroy(obj)
        obj = build(size)

    if justify:
        # Justify by stretching the WHOLE line, not by repositioning each
        # word. Placing words individually needs each word's ADVANCE, and
        # measuring its INK width instead loses the side bearing at every
        # step: words crept together until PDFium stopped seeing a boundary
        # and the text layer came back as "Excuseme!Doesanyonehereknow".
        # The page looked right; the document was unusable for copying,
        # searching, or a screen reader.
        #
        # One object holding real space CHARACTERS cannot have that problem.
        _, _, right, _ = _object_bounds(obj)
        drawn = right - left
        if drawn > 0:
            stretch = (limit - left) / drawn
            if 1.0 < stretch <= MAX_JUSTIFY_STRETCH:
                pdfium_c.FPDFPageObj_Destroy(obj)
                obj = build(size, stretch)
    return obj, size


def _widestring(text: str) -> Any:
    buffer = ctypes.create_string_buffer(text.encode("utf-16-le") + b"\x00\x00")
    return ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort))


def _standard_font_for(family: str) -> tuple[bytes, bool]:
    """The base-14 face for `family`, as bytes for the PDFium call.

    Delegates to `domain.fonts`: the fitter lays text out using that same
    mapping's measured advance, and two copies of this decision would let the
    layout and the writer pick different faces.
    """
    name, recognized = substitute_font(family)
    return name.encode("ascii"), recognized


def _strip_subset_tag(name: str) -> str:
    """`GGKEDP+DejaVuSans` -> `DejaVuSans`; anything else is returned as-is."""
    prefix, plus, rest = name.partition("+")
    if plus and len(prefix) == _SUBSET_TAG_LENGTH and prefix.isalpha() and prefix.isupper():
        return rest
    return name


def _drop_unmapped(text: str) -> str:
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


def _object_text(obj: Any, textpage: Any) -> str:
    length = pdfium_c.FPDFTextObj_GetText(obj, textpage, None, 0)
    if length <= 0:
        return ""
    buffer = ctypes.create_string_buffer(length * 2)
    pdfium_c.FPDFTextObj_GetText(
        obj, textpage, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)), length
    )
    return _drop_unmapped(buffer.raw[: length * 2].decode("utf-16-le").rstrip("\x00"))


def _is_rotated(obj: Any) -> bool:
    """Whether the text object's matrix turns or skews it.

    A pure translate-and-scale matrix has b and c at zero. Anything else is a
    rotation or a skew, and this capability lays text out in page-horizontal
    space only.
    """
    matrix = pdfium_c.FS_MATRIX()
    if not pdfium_c.FPDFPageObj_GetMatrix(obj, matrix):
        return False
    scale = math.hypot(matrix.a, matrix.b)
    if scale <= 0:
        return False
    return abs(matrix.b) / scale > _ROTATION_TOLERANCE


def _effective_font_size(obj: Any) -> float:
    """The size the text is actually DRAWN at, not the one the API reports.

    `FPDFTextObj_GetFontSize` returns the size in unscaled text space, and a
    real document scales it through the text matrix instead. Measured on a
    120-page book: every run reported **1.00** while its matrix carried the
    true 11, 13 or 14. Trusting the bare call would have redrawn the whole
    document at one point -- invisible text -- and made every width estimate
    in `fit_text_to_block` wrong by more than tenfold.

    A matplotlib-generated fixture has an identity matrix, so the bare call
    looks correct there. That is exactly why this needed a real document.

    `hypot(a, b)` rather than `a` alone so rotated text reports its true
    scale rather than its horizontal projection.
    """
    size = ctypes.c_float()
    pdfium_c.FPDFTextObj_GetFontSize(obj, size)
    matrix = pdfium_c.FS_MATRIX()
    if not pdfium_c.FPDFPageObj_GetMatrix(obj, matrix):
        return size.value
    scale = math.hypot(matrix.a, matrix.b)
    return size.value * scale if scale > 0 else size.value


def _object_bounds(obj: Any) -> tuple[float, float, float, float]:
    left, bottom, right, top = (ctypes.c_float() for _ in range(4))
    pdfium_c.FPDFPageObj_GetBounds(obj, left, bottom, right, top)
    return left.value, bottom.value, right.value, top.value


def _text_objects(page: Any, textpage: Any) -> list[tuple[Any, str, tuple[float, float, float, float]]]:
    """Every text object on the page, with its text and bounds, read once.

    Both callers -- the public read and the write's target matching -- need
    exactly this triple, and reading it in one place is what keeps their two
    views of the page from drifting apart. `textpage` must be an OPEN handle;
    both callers close it before mutating anything.
    """
    found = []
    for index in range(pdfium_c.FPDFPage_CountObjects(page.raw)):
        obj = pdfium_c.FPDFPage_GetObject(page.raw, index)
        if pdfium_c.FPDFPageObj_GetType(obj) != pdfium_c.FPDF_PAGEOBJ_TEXT:
            continue
        found.append((obj, _object_text(obj, textpage), _object_bounds(obj)))
    return found


def _match_key(text: str, left: float, bottom: float) -> tuple[str, float, float]:
    """Objects are re-read from a freshly opened document, so pointers differ
    between the read and the write. Text plus rounded position is the join."""
    return text, round(left, 1), round(bottom, 1)


class Pypdfium2TextEditAdapter:
    """`PdfTextEditPort` implementation over the raw PDFium C API."""

    def __init__(self, font_source: FontSourcePort | None = None) -> None:
        # Optional: without it, text a base-14 face cannot draw renders as
        # empty boxes and the run reports the substitution, like every other
        # missing optional toolchain here.
        self._font_source = font_source

    def _font_for(
        self, document: Any, cache: dict[Any, Any], face: bytes, bold: bool,
        italic: bool, text: str,
    ) -> tuple[Any, bool]:
        """The PDFium font handle to draw `text` with, and whether it is real.

        A real font is embedded ONCE PER DOCUMENT per face. Loading it per
        block would embed hundreds of copies of a 370KB file, which is the
        difference between a readable document and an unusable one.
        """
        embed = self._font_source is not None and needs_embedded_font(text)
        key = (face, bold, italic, embed)
        if key in cache:
            return cache[key]

        handle = None
        if embed and self._font_source is not None:
            data = self._font_source.load(face.decode("ascii"), bold, italic)
            if data:
                buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
                # `cid=True` is not optional: a simple font is single-byte, so
                # every character above U+00FF comes back as a replacement
                # mark. Measured -- Cyrillic read back as a row of the same
                # glyph until this was set.
                handle = pdfium_c.FPDFText_LoadFont(
                    document.raw, buffer, len(data), pdfium_c.FPDF_FONT_TRUETYPE, True
                )
                self._buffers.append(buffer)

        if handle:
            cache[key] = (handle, True)
        else:
            styled = _styled(face, bold, italic)
            cache[key] = (pdfium_c.FPDFText_LoadStandardFont(document.raw, styled), False)
        return cache[key]

    def read_runs(self, pdf_path: Path) -> list[TextRun]:
        runs: list[TextRun] = []
        document = pdfium.PdfDocument(str(pdf_path))
        try:
            for page_index in range(len(document)):
                page = document[page_index]
                textpage = pdfium_c.FPDFText_LoadPage(page.raw)
                try:
                    runs.extend(self._runs_on_page(page, textpage, page_index))
                finally:
                    pdfium_c.FPDFText_ClosePage(textpage)
        finally:
            document.close()
        return runs

    def _runs_on_page(self, page: Any, textpage: Any, page_index: int) -> list[TextRun]:
        found: list[TextRun] = []
        for obj, text, (left, bottom, right, top) in _text_objects(page, textpage):
            if not text.strip():
                continue
            found.append(
                TextRun(
                    text=text,
                    x=left,
                    y=bottom,
                    width=right - left,
                    height=top - bottom,
                    page=page_index,
                    font_size=_effective_font_size(obj),
                    font_family=self._family_of(obj),
                    rotated=_is_rotated(obj),
                )
            )
        return found

    def _family_of(self, obj: Any) -> str:
        """The run's font family, or "" when PDFium cannot report one.

        Uses `FPDFFont_GetBaseFontName`, NOT `FPDFFont_GetFamilyName`: the
        latter is present, returns success, and yields an empty string for
        embedded subset fonts (measured: length 1, just the terminator). A
        silently empty family would send every serif document back as sans.
        """
        font = pdfium_c.FPDFTextObj_GetFont(obj)
        if not font:
            return ""
        length = pdfium_c.FPDFFont_GetBaseFontName(font, None, 0)
        if length <= 0:
            return ""
        buffer = ctypes.create_string_buffer(length)
        pdfium_c.FPDFFont_GetBaseFontName(font, buffer, length)
        return _strip_subset_tag(buffer.value.decode("utf-8", errors="replace"))

    def write_blocks(
        self, pdf_path: Path, out_path: Path, replacements: list[BlockReplacement]
    ) -> WriteReport:
        by_page: dict[int, list[BlockReplacement]] = {}
        for replacement in replacements:
            by_page.setdefault(replacement.page, []).append(replacement)

        substituted = 0
        unrecognized = 0
        embedded = 0
        font_cache: dict[Any, Any] = {}
        # PDFium reads the font bytes lazily, so the buffers must outlive the
        # loop that created them.
        self._buffers: list[Any] = []
        document = pdfium.PdfDocument(str(pdf_path))
        try:
            for page_index, page_replacements in by_page.items():
                page = document[page_index]
                # READ phase: the textpage is opened AND CLOSED inside here,
                # before any mutation. Reordering this destroys text objects.
                targets = self._targets_for(page, page_replacements)
                # WRITE phase: textpage closed.
                for replacement, objects in targets:
                    for obj in objects:
                        pdfium_c.FPDFPage_RemoveObject(page.raw, obj)
                        pdfium_c.FPDFPageObj_Destroy(obj)
                    drawn, known, real = self._draw(
                        document, page, replacement, font_cache
                    )
                    substituted += drawn
                    unrecognized += 0 if known else 1
                    embedded += 1 if real else 0
                pdfium_c.FPDFPage_GenerateContent(page.raw)

            out_path.parent.mkdir(parents=True, exist_ok=True)
            document.save(str(out_path))
        finally:
            document.close()

        # PDFium stamps a random /ID on save; without this every byte-identity
        # test in this capability is flaky for a reason that is a real bug.
        out_path.write_bytes(normalize_pdf_id(out_path.read_bytes()))
        return WriteReport(
            blocks_written=len(replacements),
            fonts_substituted=substituted,
            fonts_unrecognized=unrecognized,
            fonts_embedded=embedded,
        )

    def _targets_for(
        self, page: Any, replacements: list[BlockReplacement]
    ) -> list[tuple[BlockReplacement, list[Any]]]:
        """Match each replacement to its page objects, then CLOSE the textpage."""
        lookup: dict[tuple[str, float, float], int] = {}
        for index, replacement in enumerate(replacements):
            for run in replacement.remove:
                lookup[_match_key(run.text, run.x, run.y)] = index

        matched: dict[int, list[Any]] = {index: [] for index in range(len(replacements))}
        textpage = pdfium_c.FPDFText_LoadPage(page.raw)
        try:
            for obj, text, (left, bottom, _, _) in _text_objects(page, textpage):
                target = lookup.get(_match_key(text, left, bottom))
                if target is not None:
                    matched[target].append(obj)
        finally:
            pdfium_c.FPDFText_ClosePage(textpage)
        return [(replacements[index], matched[index]) for index in sorted(matched)]

    def _draw(
        self, document: Any, page: Any, replacement: BlockReplacement,
        font_cache: dict[Any, Any],
    ) -> tuple[int, bool, bool]:
        family = replacement.remove[0].font_family if replacement.remove else ""
        font_name, recognized = _standard_font_for(family)
        # Matches `TextBlock._dominant`: a block goes italic only when it is
        # essentially ALL italic. A simple majority rendered whole pages in
        # italics, which reads far worse than flattened emphasis.
        total = sum(len(r.text) for r in replacement.remove)
        share = total * DOMINANT_STYLE_SHARE
        bold = sum(len(r.text) for r in replacement.remove if r.bold) >= share
        italic = sum(len(r.text) for r in replacement.remove if r.italic) >= share
        font, real = self._font_for(
            document, font_cache, font_name, bold, italic,
            " ".join(replacement.fitted.lines),
        )
        size = replacement.fitted.font_size
        lines = replacement.fitted.lines
        for line_number, line in enumerate(lines):
            obj, size = _place_within(
                document,
                font,
                line,
                size,
                _line_x(replacement, line, line_number),
                replacement.right,
                # A justified paragraph never stretches its LAST line.
                justify=(
                    replacement.alignment is Alignment.JUSTIFY
                    and line_number < len(lines) - 1
                ),
            )
            pdfium_c.FPDFPageObj_SetFillColor(obj, 0, 0, 0, 255)
            leading = replacement.line_spacing or size * _LINE_SPACING
            first = replacement.baseline or (replacement.top - size)
            # Horizontal placement already happened inside `_place_within`, so
            # this only lifts the line to its baseline.
            pdfium_c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 0, first - line_number * leading)
            pdfium_c.FPDFPage_InsertObject(page.raw, obj)
        return 1, recognized, real
