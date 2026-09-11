from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class PdfClassification:
    """What kind of document this is, before anything tries to translate it.

    `pages_with_columns` is not decoration: it marks the pages where the
    single-column block grouping in `domain/block_grouping.py` is not to be
    trusted, and the service reports those pages as unverified rather than
    presenting a guess as a result.

    `pages_needing_ocr` is ADVISORY only. A `text_based` PDF can still list
    pages here when its text layer is sparse (measured on a matplotlib PDF:
    `pdf_type="text_based"` with `pages_needing_ocr=[1]`), so `pdf_type` is
    the gate and this is context.
    """

    pdf_type: str
    page_count: int
    pages_needing_ocr: list[int]
    pages_with_columns: list[int]
    has_encoding_issues: bool


class PdfClassifyPort(Protocol):
    def classify(self, pdf_path: Path) -> PdfClassification:
        """Classify `pdf_path` without modifying it."""
        ...
