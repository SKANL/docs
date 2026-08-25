from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from docs.domain.block_grouping import TextRun
from docs.domain.text_fitting import FittedText


@dataclass(frozen=True)
class BlockReplacement:
    """Remove `remove`, then draw `fitted` starting at (`x`, `top`) on `page`."""

    page: int
    remove: list[TextRun]
    fitted: FittedText
    x: float
    top: float


@dataclass(frozen=True)
class WriteReport:
    """What the write had to compromise on, so the caller can report it."""

    blocks_written: int
    fonts_substituted: int
    fonts_unrecognized: int = 0
    """Blocks whose original family matched no known face and fell back to
    Helvetica. A serif document silently turning sans-serif on every page is
    exactly the kind of degradation this harness refuses to hide."""


class PdfTextEditPort(Protocol):
    def read_runs(self, pdf_path: Path) -> list[TextRun]:
        """Every text object in the document, with page-space geometry."""
        ...

    def write_blocks(
        self, pdf_path: Path, out_path: Path, replacements: list[BlockReplacement]
    ) -> WriteReport:
        """Apply `replacements` to `pdf_path` and write `out_path`.

        The written bytes MUST be deterministic: an implementation is required
        to end in `domain.pdf_id.normalize_pdf_id`, because PDFium stamps a
        random trailer `/ID` on every save. `tests/architecture/
        test_pdf_writer_invariant.py` enforces that mechanically.
        """
        ...
