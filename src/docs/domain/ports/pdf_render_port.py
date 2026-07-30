from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PdfRenderPort(Protocol):
    def render_pages(
        self,
        pdf_path: Path,
        out_dir: Path,
        dpi: int = 150,
        pages: str | None = None,
        autotrim: bool = True,
    ) -> list[Path]:
        """Render pages of `pdf_path` to raster PNGs under `out_dir` and
        return the written paths in page order.

        Complements the text-extraction ingest path: when a figure's source
        PDF holds vector diagrams (no embedded raster to pull out), rendering
        the page itself is the only way to get an image.

        - `dpi` sets the render resolution (scale = dpi / 72).
        - `pages=None` renders every page. Otherwise a 1-based spec like
          "1-3,5" selects a subset; ranges expand inclusively and the result
          is de-duplicated and returned in ascending page order.
        - `autotrim=True` crops surrounding whitespace (diff against white,
          bbox, small padding); a page that is entirely blank is kept as-is.

        Output names are deterministic and stable: `<pdf-stem>-p<NN>.png`
        (1-based, zero-padded to two digits), so the same input always
        produces byte-identical files.
        """
        ...
