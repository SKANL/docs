# src/docs/infrastructure/fonts/dejavu_font_source.py
"""Real font files for the faces a base-14 substitute cannot draw.

A base-14 face is encoded WinAnsi, so it can draw Spanish, French, German and
Portuguese and cannot draw a single character of Russian, Greek or Ukrainian --
those come out as empty boxes. Embedding a real font is the only way to
translate into them at all.

The fonts come from **matplotlib**, which is already a hard dependency of this
project and ships the complete DejaVu family: Serif, Sans and Mono in four
styles each, covering Latin, Cyrillic and Greek under a free licence.

That choice is not convenience, it is determinism. Reading fonts from the
operating system would make the output depend on which fonts a machine
happens to have installed, and this harness promises byte-identical reruns.
A font that arrives with a declared dependency is the same font everywhere.

# ponytail: DejaVu's coverage IS the boundary of this capability, not a step
# towards a wider one. Anything it cannot draw draws a box and is counted.
# Deliberately not pursued:
#
# - Scripts DejaVu lacks (CJK, Arabic, Hebrew). Adding them means bundling a
#   Noto face larger than this whole project, for a target nobody has asked
#   for.
# - Per-glyph face selection. Coverage differs BETWEEN DejaVu faces -- Sans
#   carries the ballot box, Serif does not -- so a serif block containing one
#   still shows a box. Measured on a diagram page: the female sign resolved,
#   the ballot boxes did not. Choosing a face per glyph needs a font library
#   to ask about coverage; three symbols on three pages of one book do not
#   justify one.
#
# Both are limits with a measurement behind them, not a backlog.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from docs.domain.fonts import COURIER, HELVETICA, TIMES

# (base-14 face, bold, italic) -> the DejaVu file that stands in for it.
_FACES = {
    (TIMES, False, False): "DejaVuSerif.ttf",
    (TIMES, True, False): "DejaVuSerif-Bold.ttf",
    (TIMES, False, True): "DejaVuSerif-Italic.ttf",
    (TIMES, True, True): "DejaVuSerif-BoldItalic.ttf",
    (HELVETICA, False, False): "DejaVuSans.ttf",
    (HELVETICA, True, False): "DejaVuSans-Bold.ttf",
    (HELVETICA, False, True): "DejaVuSans-Oblique.ttf",
    (HELVETICA, True, True): "DejaVuSans-BoldOblique.ttf",
    (COURIER, False, False): "DejaVuSansMono.ttf",
    (COURIER, True, False): "DejaVuSansMono-Bold.ttf",
    (COURIER, False, True): "DejaVuSansMono-Oblique.ttf",
    (COURIER, True, True): "DejaVuSansMono-BoldOblique.ttf",
}


@lru_cache(maxsize=1)
def _font_dir() -> Path | None:
    """Where matplotlib keeps its bundled TrueType files, or `None`.

    Guarded like every other optional path in this project: matplotlib is a
    declared dependency, but an import failure must degrade this capability
    rather than break the command.
    """
    try:
        import matplotlib
    except Exception:
        return None
    directory = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    return directory if directory.is_dir() else None


class DejaVuFontSource:
    """`FontSourcePort` over matplotlib's bundled DejaVu family."""

    @lru_cache(maxsize=len(_FACES))  # noqa: B019
    def load(self, face: str, bold: bool, italic: bool) -> bytes | None:
        """The font file's bytes, or `None` when it cannot be found.

        Cached because the same face is asked for once per block and the files
        run to hundreds of kilobytes; reading one per block would dominate the
        run.
        """
        directory = _font_dir()
        filename = _FACES.get((face, bold, italic))
        if directory is None or filename is None:
            return None
        path = directory / filename
        try:
            return path.read_bytes()
        except OSError:
            return None
