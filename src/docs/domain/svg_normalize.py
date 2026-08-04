# src/docs/domain/svg_normalize.py
from __future__ import annotations

import re

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_METADATA_RE = re.compile(r"<metadata>.*?</metadata>", re.DOTALL)
_ID_DEF_RE = re.compile(r'id="([^"]+)"')


def normalize_svg(text: str) -> str:
    """The determinism spike (design.md Decision "normalize_svg lives in
    domain"): makes two renderer-produced SVGs of the same diagram
    byte-identical despite tool-generated ids/comments/metadata timestamps
    that vary run-to-run. Pure, order-preserving, byte-stable.

    1. strip XML comments (tool-version/wall-clock banners).
    2. strip `<metadata>...</metadata>` (matplotlib RDF `dc:date`).
    3. collect every `id="X"` in first-appearance order, map to `n0, n1, ...`
       and rewrite each definition and reference (`#X`, `url(#X)`,
       `href="X"`/`href="#X"`, `xlink:href="#X"`, `aria-labelledby="X"`),
       replacing LONGEST-id-first: a longer id containing a shorter id as a
       substring (e.g. "abc" containing "a") is fully replaced away before
       the shorter id's own replacement runs, so a bare `#X` reference (the
       one form with no closing delimiter, e.g. a mermaid CSS id selector)
       can never partially match inside a longer id's text.

    # ponytail: regex over ids, not a full XML parser -- upgrade to
    # defusedxml if an id ever leaks past this anchored pattern.
    """
    text = _COMMENT_RE.sub("", text)
    text = _METADATA_RE.sub("", text)

    ids: list[str] = []
    seen: set[str] = set()
    for match in _ID_DEF_RE.finditer(text):
        old_id = match.group(1)
        if old_id not in seen:
            seen.add(old_id)
            ids.append(old_id)

    mapping = {old_id: f"n{i}" for i, old_id in enumerate(ids)}

    for old_id in sorted(ids, key=len, reverse=True):
        new_id = mapping[old_id]
        text = text.replace(f'id="{old_id}"', f'id="{new_id}"')
        text = text.replace(f'href="{old_id}"', f'href="{new_id}"')
        text = text.replace(f'aria-labelledby="{old_id}"', f'aria-labelledby="{new_id}"')
        # Covers every remaining reference form sharing the `#X` substring:
        # `url(#X)`, `href="#X"`, `xlink:href="#X"`, and bare `#X` (e.g. a
        # mermaid CSS id selector `#X{...}`).
        text = text.replace(f"#{old_id}", f"#{new_id}")

    return text
