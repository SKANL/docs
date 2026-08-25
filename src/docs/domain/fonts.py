# src/docs/domain/fonts.py
"""Which base-14 face replaces an embedded one, and how wide it draws.

Substitution is not a choice. An embedded font is a SUBSET carrying only the
glyphs the document already used: writing Spanish into one renders
`"PRUEA de centos[]cncin[]o[]u[]"` -- not merely the accents, the lowercase
"a" is absent too. So every block is redrawn in a base-14 face, and the only
question is which one.

The family NAME is the signal. PDFium exposes descriptor flags that should
answer this and they are wrong in real files: `Courier` reported
`FixedPitch=False` and `Baskerville` reported `Serif=False`. Both false.

The advance ratios below were MEASURED from PDFium at 100pt over a sample of
Spanish prose, not looked up. They matter because the text is laid out before
it is drawn: estimating the wrap with the SOURCE font's metrics and then
drawing in a substitute with different ones pushed ink 100px past the right
margin on every dialogue page of a real book.

Pure data. No I/O, no imports from other layers.
"""
from __future__ import annotations

TIMES = "Times-Roman"
HELVETICA = "Helvetica"
COURIER = "Courier"

_SERIF_FAMILIES = (
    "times", "serif", "georgia", "garamond", "baskerville", "palatino",
    "caslon", "bodoni", "didot", "minion", "cambria", "book", "roman",
    "century", "clarendon", "utopia", "charter", "hoefler", "sabon", "hiramin",
)
_MONO_FAMILIES = ("courier", "mono", "consolas", "menlo", "monaco", "typewriter")
_SANS_FAMILIES = (
    "helvetica", "arial", "optima", "sans", "verdana", "tahoma", "calibri",
    "futura", "gill", "frutiger", "univers", "myriad", "lato", "roboto", "dejavu",
)

ITALIC_MARKERS = ("italic", "oblique")
BOLD_MARKERS = ("bold", "black", "heavy", "semibold")

# Mean glyph advance as a fraction of type size, measured from PDFium over
# Spanish prose. Bold is wider than regular, and a monospace face is wider
# than either -- using one number for all three misjudges every mixed page.
_ADVANCE = {
    (TIMES, False): 0.4075,
    (TIMES, True): 0.4376,
    (HELVETICA, False): 0.4549,
    (HELVETICA, True): 0.4875,
    (COURIER, False): 0.5982,
    (COURIER, True): 0.5982,
}

# Last-resort width for a block whose family says nothing. Deliberately the
# widest of the three, so an unknown face wraps early rather than overruns.
_FALLBACK_ADVANCE = 0.5982


def has_marker(name: str, markers: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in markers)


def substitute_font(family: str) -> tuple[str, bool]:
    """`(base-14 face, whether the family was recognised)`.

    An unrecognised family becomes Helvetica, which turns a serif document
    sans-serif across every page -- so the caller reports the count rather
    than letting a wrong guess pass unseen.
    """
    lowered = family.lower()
    for needle in _MONO_FAMILIES:
        if needle in lowered:
            return COURIER, True
    for needle in _SERIF_FAMILIES:
        if needle in lowered:
            return TIMES, True
    for needle in _SANS_FAMILIES:
        if needle in lowered:
            return HELVETICA, True
    return HELVETICA, False


def advance_ratio_for(family: str) -> float:
    """How wide the SUBSTITUTE draws, which is the only width that matters.

    The source font's own measured advance is irrelevant here: it is not the
    font that ends up on the page.
    """
    face, recognized = substitute_font(family)
    if not recognized:
        return _FALLBACK_ADVANCE
    return _ADVANCE[(face, has_marker(family, BOLD_MARKERS))]
