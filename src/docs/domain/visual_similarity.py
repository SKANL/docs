# src/docs/domain/visual_similarity.py
"""Measure whether two rendered pages have the same LAYOUT.

"The translated PDF looks like the original" is the headline promise of this
capability, and a promise nobody measures is a promise nobody keeps. The
existing `PdfRenderPort.render_pages` already rasterizes pages to PNG, so the
gate costs one comparison.

The obvious metric is wrong, and was wrong here in production: mean absolute
pixel difference scored **0.9905** on a page whose chart axis labels had been
collapsed into one corner and whose sentence read "fi nance team Prepared by
the". On a mostly-white page, averaging over every pixel dilutes any disaster
into nothing. A gate that cannot fail is not a gate.

What this measures instead is WHERE THE INK IS, not which glyphs are in it:
both pages are reduced to a coarse grid of ink density and those grids are
compared. That is the right question, because the glyphs are SUPPOSED to
change -- the text was translated -- while their position on the page is
supposed not to. Text moving to a different part of the page moves ink between
cells and shows up immediately; the same sentence rendered in another language
does not.

**What this is NOT.** Measured on one real document: the layout-destroyed
output scored 0.8015 and the correct translation scored 0.8253. A 0.02 margin
is noise, not a threshold -- translated text legitimately changes length and
moves ink, and no ink-distribution metric separates "re-wrapped correctly"
from "moved to the wrong place" at a usable margin. Treat this as a
DIAGNOSTIC, not a pass/fail gate, and put a loose floor on it to catch total
collapse only. The invariants worth gating on are structural and exact --
page count, page geometry, and the preservation of every non-text page object
-- and they live in the adapter's tests, where they can be proven rather than
estimated.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

# Grid resolution. Fine enough that a block sliding across the page lands in
# different cells, coarse enough that re-wrapped words inside the same
# paragraph do not.
GRID_COLUMNS = 24
GRID_ROWS = 32

_WHITE = 255.0


def _ink_grid(path: Path) -> list[float]:
    """Ink density per grid cell, 0.0 (blank) to 1.0 (solid)."""
    with Image.open(path) as image:
        grey = image.convert("L")
        # BOX averages every source pixel into its cell, so this IS the
        # density -- not a sample that could miss a thin line.
        cells = grey.resize((GRID_COLUMNS, GRID_ROWS), Image.Resampling.BOX)
        # `tobytes()`, not `getdata()`: the latter is deprecated for removal in
        # Pillow 14, and `filterwarnings = ["error"]` correctly turns that into
        # a failing test rather than a future outage. An "L" image is one byte
        # per pixel, so the raw buffer IS the grey values.
        raw = cells.tobytes()
    return [(_WHITE - value) / _WHITE for value in raw]


def page_similarity(before_png: Path, after_png: Path) -> float:
    """Return layout similarity in `[0.0, 1.0]`, where 1.0 is identical.

    Pages of different sizes score 0.0: a page-geometry change is a total
    failure of the promise, not a small difference to average away.

    Two blank pages score 1.0 -- they are identical, and calling that a
    failure would fail every cover page and every page break.
    """
    with Image.open(before_png) as before_image, Image.open(after_png) as after_image:
        if before_image.size != after_image.size:
            return 0.0

    before = _ink_grid(before_png)
    after = _ink_grid(after_png)

    total_ink = sum(before) + sum(after)
    if total_ink == 0.0:
        return 1.0
    # Bray-Curtis: 0 when the two ink distributions coincide, 1 when they are
    # disjoint. Normalizing by the INK rather than by the page is the whole
    # point -- it is what stops a sea of white from hiding the difference.
    displaced = sum(abs(a - b) for a, b in zip(before, after, strict=True))
    return 1.0 - (displaced / total_ink)
