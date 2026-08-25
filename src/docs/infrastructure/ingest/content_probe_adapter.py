# src/docs/infrastructure/ingest/content_probe_adapter.py
from __future__ import annotations

import re
import zipfile
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


# A `.docx` is an OPC package: a zip whose parts include the main document.
# Checking the container costs one zip open and answers the question the
# extension only claims to answer.
_CONTAINER_PARTS = {"docx": "word/document.xml"}


def _container_ok(path: Path, extension: str) -> bool:
    """Whether `path` opens as the container `extension` implies.

    Fail-open in every direction the port demands: an extension with no
    container, a missing file, or an unreadable one all report True. Only a
    file that opens as a zip WITHOUT its required part -- or does not open as
    a zip at all while claiming to -- is reported False.
    """
    required = _CONTAINER_PARTS.get(extension)
    if required is None or not path.is_file():
        return True
    try:
        with zipfile.ZipFile(path) as archive:
            return required in archive.namelist()
    except zipfile.BadZipFile:
        return False
    except OSError:  # pragma: no cover - unreadable file, not a wrong format
        return True


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
            return ContentSignals(
                extension=extension,
                pdf_title=pdf_title,
                first_headings=first_headings,
                container_ok=_container_ok(path, extension),
            )
        if extension in _TEXT_EXTENSIONS:
            return ContentSignals(
                extension=extension,
                head_keywords=self._probe_text(path),
                container_ok=_container_ok(path, extension),
            )
        return ContentSignals(extension=extension, container_ok=_container_ok(path, extension))

    def _probe_pdf(self, path: Path) -> tuple[str, tuple[str, ...]]:
        try:
            pdf = pdfium.PdfDocument(str(path))
        except Exception:
            return "", ()
        try:
            title = pdf.get_metadata_value("Title") or ""
            headings = tuple(
                heading
                for heading in (bookmark.get_title() for bookmark in islice(pdf.get_toc(), _MAX_HEADINGS))
                if heading
            )
            return title, headings
        except Exception:
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
