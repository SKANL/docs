from __future__ import annotations

from typing import Protocol


class FontSourcePort(Protocol):
    """Supplies real font files for text a base-14 face cannot draw.

    Needed only for correctness, never for taste: a base-14 face is encoded
    WinAnsi and renders Russian, Greek or Ukrainian as empty boxes. Latin
    targets never reach this port.
    """

    def load(self, face: str, bold: bool, italic: bool) -> bytes | None:
        """The TrueType bytes for one face, or `None` when unavailable.

        `None` is not an error: the caller falls back to the base-14 face and
        reports the substitution, exactly as it does for every other missing
        optional toolchain in this project.
        """
        ...
