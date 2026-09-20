from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from docs.domain.alignment import Alignment
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
    baseline: float = 0.0
    """The first line's exact baseline. `top - font_size` is about a point
    off, because `top` is the top of the ink."""
    line_spacing: float | None = None
    """The leading to DRAW with, already scaled to `fitted.font_size`, or
    `None` to fall back to a constant. Not the block's raw measurement: a
    heading that had to shrink needs its baselines to shrink with it."""
    first_line_x: float = 0.0
    """Where line 0 starts. Differs from `x` under a hanging indent."""
    right: float = 0.0
    alignment: Alignment = Alignment.LEFT
    """A PDF stores no alignment, only placement, so redrawing every block at
    its left edge slides every centred title and page number leftwards the
    moment the text length changes."""


@dataclass(frozen=True)
class WriteDiagnostic:
    """Stable geometry evidence for one unsafe post-save replacement."""

    code: str
    page: int
    replacement_index: int
    bounds: tuple[float, float, float, float]
    reference_bounds: tuple[float, float, float, float]
    object_index: int | None = None

    def to_line(self) -> str:
        bounds = ",".join(f"{value:.1f}" for value in self.bounds)
        reference = ",".join(f"{value:.1f}" for value in self.reference_bounds)
        object_detail = "" if self.object_index is None else f" objeto {self.object_index}"
        return (
            f"pagina {self.page} reemplazo {self.replacement_index + 1} {self.code}"
            f"{object_detail} bounds=({bounds}) reference=({reference})"
        )


@dataclass(frozen=True)
class WriteReport:
    """What the write had to compromise on, so the caller can report it."""

    blocks_written: int
    fonts_substituted: int
    fonts_embedded: int = 0
    """Blocks drawn with a REAL font because no base-14 face could render
    them. Ordinary Latin text never reaches this; it is coverage, not taste."""
    fonts_unrecognized: int = 0
    """Blocks whose original family matched no known face and fell back to
    Helvetica. A serif document silently turning sans-serif on every page is
    exactly the kind of degradation this harness refuses to hide."""
    verification_diagnostics: tuple[WriteDiagnostic, ...] = ()

    @property
    def blocks_unsafe(self) -> int:
        return len({item.replacement_index for item in self.verification_diagnostics})


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
