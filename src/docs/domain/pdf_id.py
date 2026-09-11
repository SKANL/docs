# src/docs/domain/pdf_id.py
"""Deterministic PDF file-identifier normalization.

PDFium writes a RANDOM `/ID` into the trailer on every save, so two runs over
identical input differ in exactly those bytes and nowhere else (measured on
this repo: same 1758-byte file, first difference at offset 1662, only the
trailer `/ID` array; `/CreationDate` is inherited from the source and is
stable). This is the PDF analogue of the `.docx` zip-timestamp problem -- a
"flaky" byte-identity test here is a product bug, not test noise.

The replacement is the same LENGTH as what it replaces, so every xref byte
offset in the file stays valid and the document still opens.

Pure data. No I/O, no imports from other layers.
"""
from __future__ import annotations

import hashlib
import re

_ID_RE = re.compile(rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\]")


def normalize_pdf_id(raw: bytes) -> bytes:
    """Replace the trailer `/ID` pair with a content-derived digest.

    A file with no `/ID` array is returned unchanged rather than raising:
    absence is valid PDF, not an error.

    Idempotent by construction -- the identifiers are zeroed before hashing,
    so re-normalizing an already-normalized file computes the same digest.
    """
    match = _ID_RE.search(raw)
    if match is None:
        return raw

    first, second = match.group(1), match.group(2)
    # Zero the identifiers before hashing so the digest depends on the
    # document's real content and never on the value being replaced.
    neutral = (
        raw[: match.start(1)]
        + b"0" * len(first)
        + raw[match.end(1) : match.start(2)]
        + b"0" * len(second)
        + raw[match.end(2) :]
    )
    digest = hashlib.sha256(neutral).hexdigest().upper().encode("ascii")
    return (
        raw[: match.start(1)]
        + digest[: len(first)]
        + raw[match.end(1) : match.start(2)]
        + digest[: len(second)]
        + raw[match.end(2) :]
    )
