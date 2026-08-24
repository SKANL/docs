# src/docs/domain/tool_versions.py
"""Which versions of the external toolchains this harness actually needs.

`docs doctor` reported whether a tool was FOUND and never whether it was
USABLE -- the same mistake `safe_style_name` made about paragraph styles, and
it costs the same way. A first CI run put pandoc 3.1.3 next to a developer's
3.10 and 13 tests died; a user on pandoc 2.9 would get `pandoc: OK` followed
by an HTML build that fails, or a document that quietly differs.

Every floor here is derived from something the code does, never from taste.
Pure parsing and comparison: reading a version is a subprocess, and that
lives behind `ToolResolverPort`.
"""
from __future__ import annotations

import re

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")

# The oldest release that supports what the harness invokes.
#
#   pandoc  -- `html_render` passes `--embed-resources`, added in 2.19.
#              (Before that the flag was `--self-contained`.)
#
# Deliberately only what is EVIDENCED. LibreOffice, Java, mmdc and resvg have
# no known floor because nothing in this harness uses a version-gated feature
# of them; inventing numbers would turn a real check into superstition, and
# would fail a working install to satisfy a guess.
MINIMUM_VERSIONS: dict[str, tuple[int, ...]] = {
    "pandoc": (2, 19),
}


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """The first dotted number in a tool's `--version` output.

    Tools disagree about shape -- `pandoc 3.10`, `LibreOffice 7.4.7.2
    40(Build:2)`, `openjdk version "17.0.9"` -- and they agree only that the
    version is the first dotted number. Anything else returns None, which
    every caller must read as "unknown", never as "too old".
    """
    if not text:
        return None
    match = _VERSION_RE.search(text)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def version_meets(found: tuple[int, ...] | None, minimum: tuple[int, ...]) -> bool | None:
    """Whether `found` is at least `minimum`. `None` means unknown, not old.

    Component-wise, never lexical: `"3.10" < "3.9"` as strings, and pandoc
    3.10 is newer than 3.9. A string comparison would report a modern
    toolchain as too old and send someone to upgrade what is already newest.
    """
    if found is None:
        return None
    width = max(len(found), len(minimum))
    padded_found = found + (0,) * (width - len(found))
    padded_minimum = minimum + (0,) * (width - len(minimum))
    return padded_found >= padded_minimum


def describe_version(found: tuple[int, ...] | None) -> str:
    """`(3, 1, 3)` -> `"3.1.3"`, unknown -> `"versión desconocida"`."""
    return ".".join(str(part) for part in found) if found else "versión desconocida"
