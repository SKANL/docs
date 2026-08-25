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
_STANDARD_FONTS = (
    ("times", b"Times-Roman"),
    ("serif", b"Times-Roman"),
    ("georgia", b"Times-Roman"),
    ("garamond", b"Times-Roman"),
    ("courier", b"Courier"),
    ("mono", b"Courier"),
    ("consolas", b"Courier"),
)
_DEFAULT_FONT = b"Helvetica"


def _widestring(text: str) -> Any:
    buffer = ctypes.create_string_buffer(text.encode("utf-16-le") + b"\x00\x00")
    return ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort))


def _standard_font_for(family: str) -> bytes:
    """Map an embedded family onto a base-14 font.

    Phase 1 ALWAYS substitutes -- no path here reuses the original embedded
    font -- so the caller counts every written block as a substitution. That
    number is meant to look large: it is the honest size of the compromise,
    not a metric to tune down.
    """
    lowered = family.lower()
    for needle, font in _STANDARD_FONTS:
        if needle in lowered:
            return font
    return _DEFAULT_FONT


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
            size = ctypes.c_float()
            pdfium_c.FPDFTextObj_GetFontSize(obj, size)
            found.append(
                TextRun(
                    text=text,
                    x=left,
                    y=bottom,
                    width=right - left,
                    height=top - bottom,
                    page=page_index,
                    font_size=size.value,
                    font_family=self._family_of(obj),
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
                    substituted += self._draw(document, page, replacement)
                pdfium_c.FPDFPage_GenerateContent(page.raw)

            out_path.parent.mkdir(parents=True, exist_ok=True)
            document.save(str(out_path))
        finally:
            document.close()

        # PDFium stamps a random /ID on save; without this every byte-identity
        # test in this capability is flaky for a reason that is a real bug.
        out_path.write_bytes(normalize_pdf_id(out_path.read_bytes()))
        return WriteReport(blocks_written=len(replacements), fonts_substituted=substituted)

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

    def _draw(self, document: Any, page: Any, replacement: BlockReplacement) -> int:
        family = replacement.remove[0].font_family if replacement.remove else ""
        font = pdfium_c.FPDFText_LoadStandardFont(document.raw, _standard_font_for(family))
        size = replacement.fitted.font_size
        for line_number, line in enumerate(replacement.fitted.lines):
            obj = pdfium_c.FPDFPageObj_CreateTextObj(document.raw, font, size)
            pdfium_c.FPDFText_SetText(obj, _widestring(line))
            pdfium_c.FPDFPageObj_SetFillColor(obj, 0, 0, 0, 255)
            baseline = replacement.top - size - (line_number * size * _LINE_SPACING)
            pdfium_c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, replacement.x, baseline)
            pdfium_c.FPDFPage_InsertObject(page.raw, obj)
        return 1
