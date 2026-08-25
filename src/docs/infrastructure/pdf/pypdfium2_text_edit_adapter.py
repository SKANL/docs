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

from docs.domain.block_grouping import TextRun
from docs.domain.pdf_id import normalize_pdf_id
from docs.domain.ports.pdf_text_edit_port import BlockReplacement, WriteReport

_LINE_SPACING = 1.18

# Subset tags are exactly six uppercase letters followed by "+".
_SUBSET_TAG_LENGTH = 6

# Original fonts are embedded as SUBSETS holding only the glyphs the document
# already used, so a target-language glyph that never appeared is simply not
# there. Map the family onto a base-14 standard font, which always carries
# full Latin coverage, and count the substitution.
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
_SERIF_FAMILIES = (
    "times", "serif", "georgia", "garamond", "baskerville", "palatino",
    "caslon", "bodoni", "didot", "minion", "cambria", "book", "roman",
    "century", "clarendon", "utopia", "charter", "hoefler", "sabon", "hiramin",
)
_MONO_FAMILIES = ("courier", "mono", "consolas", "menlo", "monaco", "typewriter")
_SANS_FAMILIES = (
    "helvetica", "arial", "optima", "sans", "verdana", "tahoma", "calibri",
    "futura", "gill", "frutiger", "univers", "myriad", "lato", "roboto", "dejavu",
)
_DEFAULT_FONT = b"Helvetica"

# Base-14 covers four styles per family, so italic and bold survive the
# substitution instead of being flattened. The source book distinguishes
# spoken words from inner thought purely with italics; dropping that loses
# meaning the author put there deliberately.
_BASE14 = {
    b"Times-Roman": (b"Times-Roman", b"Times-Bold", b"Times-Italic", b"Times-BoldItalic"),
    b"Helvetica": (b"Helvetica", b"Helvetica-Bold", b"Helvetica-Oblique", b"Helvetica-BoldOblique"),
    b"Courier": (b"Courier", b"Courier-Bold", b"Courier-Oblique", b"Courier-BoldOblique"),
}

# The base font name is where style lives: `Baskerville-Italic`, `Optima-Bold`.
_ITALIC_MARKERS = ("italic", "oblique")
_BOLD_MARKERS = ("bold", "black", "heavy", "semibold")


def _styled(font: bytes, bold: bool, italic: bool) -> bytes:
    regular, bold_face, italic_face, both = _BASE14[font]
    if bold and italic:
        return both
    if bold:
        return bold_face
    if italic:
        return italic_face
    return regular


def _widestring(text: str) -> Any:
    buffer = ctypes.create_string_buffer(text.encode("utf-16-le") + b"\x00\x00")
    return ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort))


def _standard_font_for(family: str) -> tuple[bytes, bool]:
    """Map an embedded family onto a base-14 font.

    Returns `(font, recognised)`. Phase 1 ALWAYS substitutes -- no path here
    reuses the original embedded font -- so the caller counts every written
    block as a substitution. That number is meant to look large: it is the
    honest size of the compromise, not a metric to tune down.

    `recognised` is separate and matters more: an unknown family silently
    becomes Helvetica, which turns a serif document sans-serif across every
    page. The caller reports the count so a wrong guess is visible instead of
    being discovered by reading the output.

    # ponytail: a name list, because the descriptor flags that should answer
    # this are wrong in real files. Widen the lists when a document shows a
    # family they miss; the report names it.
    """
    lowered = family.lower()
    for needle in _MONO_FAMILIES:
        if needle in lowered:
            return b"Courier", True
    for needle in _SERIF_FAMILIES:
        if needle in lowered:
            return b"Times-Roman", True
    for needle in _SANS_FAMILIES:
        if needle in lowered:
            return _DEFAULT_FONT, True
    return _DEFAULT_FONT, False


def _style_of(family: str) -> tuple[bool, bool]:
    """`(bold, italic)` read from the base font name.

    The name is where style lives in these files: `Baskerville-Italic`,
    `Optima-Bold`. The descriptor flags that should say so are wrong (measured:
    `Courier` claimed FixedPitch=False), so the name is the honest signal.
    """
    lowered = family.lower()
    return (
        any(marker in lowered for marker in _BOLD_MARKERS),
        any(marker in lowered for marker in _ITALIC_MARKERS),
    )


def _strip_subset_tag(name: str) -> str:
    """`GGKEDP+DejaVuSans` -> `DejaVuSans`; anything else is returned as-is."""
    prefix, plus, rest = name.partition("+")
    if plus and len(prefix) == _SUBSET_TAG_LENGTH and prefix.isalpha() and prefix.isupper():
        return rest
    return name


def _object_text(obj: Any, textpage: Any) -> str:
    length = pdfium_c.FPDFTextObj_GetText(obj, textpage, None, 0)
    if length <= 0:
        return ""
    buffer = ctypes.create_string_buffer(length * 2)
    pdfium_c.FPDFTextObj_GetText(
        obj, textpage, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)), length
    )
    return buffer.raw[: length * 2].decode("utf-16-le").rstrip("\x00")


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
            family = self._family_of(obj)
            bold, italic = _style_of(family)
            found.append(
                TextRun(
                    text=text,
                    x=left,
                    y=bottom,
                    width=right - left,
                    height=top - bottom,
                    page=page_index,
                    font_size=_effective_font_size(obj),
                    font_family=family,
                    bold=bold,
                    italic=italic,
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
                    drawn, known = self._draw(document, page, replacement)
                    substituted += drawn
                    unrecognized += 0 if known else 1
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

    def _draw(self, document: Any, page: Any, replacement: BlockReplacement) -> tuple[int, bool]:
        family = replacement.remove[0].font_family if replacement.remove else ""
        font_name, recognized = _standard_font_for(family)
        run = replacement.remove[0] if replacement.remove else None
        styled = _styled(font_name, bool(run and run.bold), bool(run and run.italic))
        font = pdfium_c.FPDFText_LoadStandardFont(document.raw, styled)
        size = replacement.fitted.font_size
        for line_number, line in enumerate(replacement.fitted.lines):
            obj = pdfium_c.FPDFPageObj_CreateTextObj(document.raw, font, size)
            pdfium_c.FPDFText_SetText(obj, _widestring(line))
            pdfium_c.FPDFPageObj_SetFillColor(obj, 0, 0, 0, 255)
            baseline = replacement.top - size - (line_number * size * _LINE_SPACING)
            pdfium_c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, replacement.x, baseline)
            pdfium_c.FPDFPage_InsertObject(page.raw, obj)
        return 1, recognized
