# src/docs/infrastructure/ingest/content_probe_adapter.py
from __future__ import annotations

import re
from itertools import islice
from pathlib import Path

import pypdfium2 as pdfium

from docs.domain.ports.content_probe_port import ContentSignals

# First-N-bytes budget for the text/markdown keyword scan and the PDF TOC
# heading cap (design.md ADR-D / §4 "Content probe reads differ by
# platform/locale... probe failures -> empty signals, fail-open"). Small,
# fixed, deterministic -- never reads a whole large file.
_HEAD_BYTES = 4000
_MAX_HEADINGS = 5
_TEXT_EXTENSIONS = frozenset({"md", "txt"})
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


class FilesystemContentProbeAdapter:
    """`ContentProbePort` implementation. PR1 surface (item E's manual
    auto-detect): the file extension. PR4 (item D) extends the SAME
    adapter with PDF title/heading extraction (`pypdfium2`, already a hard
    dependency for figure rendering) and a first-N-bytes keyword scan for
    text/markdown -- never a second port.

    Fail-open (design.md §4): any read/parse failure returns empty content
    fields (extension still reported) instead of raising, so a single
    unreadable or malformed file never breaks a doctor run or an ingest
    walk. Output is raw, case-folded strings only -- the domain classifier
    (`source_role.py`) owns lexicon matching and accent folding, keeping
    this adapter role-agnostic (ADR-D "Signals-as-strings boundary")."""

    def probe(self, path: Path) -> ContentSignals:
        try:
            extension = path.suffix.lower().lstrip(".")
        except (OSError, ValueError):
            return ContentSignals()
        if extension == "pdf":
            pdf_title, first_headings = self._probe_pdf(path)
            return ContentSignals(extension=extension, pdf_title=pdf_title, first_headings=first_headings)
        if extension in _TEXT_EXTENSIONS:
            return ContentSignals(extension=extension, head_keywords=self._probe_text(path))
        return ContentSignals(extension=extension)

    def _probe_pdf(self, path: Path) -> tuple[str, tuple[str, ...]]:
        try:
            pdf = pdfium.PdfDocument(str(path))
        except Exception:  # noqa: BLE001 -- pypdfium2 raises its own error types on malformed PDFs
            return "", ()
        try:
            title = pdf.get_metadata_value("Title") or ""
            headings = tuple(
                heading
                for heading in (bookmark.get_title() for bookmark in islice(pdf.get_toc(), _MAX_HEADINGS))
                if heading
            )
            return title, headings
        except Exception:  # noqa: BLE001 -- fail-open on any pdfium read error (design.md §4)
            return "", ()
        finally:
            pdf.close()

    def _probe_text(self, path: Path) -> tuple[str, ...]:
        try:
            data = path.read_bytes()[:_HEAD_BYTES]
        except OSError:
            return ()
        text = data.decode("utf-8", errors="replace").casefold()
        return tuple(sorted(set(_WORD_RE.findall(text))))
