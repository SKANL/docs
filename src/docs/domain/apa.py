from __future__ import annotations

import re

from docs.domain.markdown_text import clean_markdown_text, normalize_author_key

_PARENTHETICAL_RE = re.compile(r"\(([^()]*?,\s*(?:19|20)\d{2}[a-z]?[^()]*)\)")
_NARRATIVE_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñüÜ'\-]+(?:\s+et\s+al\.)?)\s+\(((?:19|20)\d{2}[a-z]?)\)"
)
_REFERENCES_HEADING_RE = re.compile(
    r"^#+\s+REFERENCIAS(?:\s+BIBLIOGR[ÁA]FICAS)?\s*$", re.IGNORECASE | re.MULTILINE
)
_DATED_ENTRY_RE = re.compile(r"\((?:19|20)\d{2}|n\.d\.\)", re.IGNORECASE)
_ET_AL_RE = re.compile(r"\bet\s+al\.$", re.IGNORECASE)


def extract_apa_citations(text: str) -> set[str]:
    citations: set[str] = set()
    for match in _PARENTHETICAL_RE.finditer(text):
        citation = clean_markdown_text(match.group(1))
        if citation:
            citations.add(citation)
    for match in _NARRATIVE_RE.finditer(text):
        citations.add(f"{match.group(1)}, {match.group(2)}")
    return citations


def extract_references_block(text: str) -> str:
    matches = list(_REFERENCES_HEADING_RE.finditer(text))
    if not matches:
        return ""
    match = matches[-1]
    return text[match.end():]


def extract_reference_entries(text: str) -> list[str]:
    block = extract_references_block(text)
    entries: list[str] = []
    for line in block.splitlines():
        stripped = clean_markdown_text(line)
        if not stripped or stripped.startswith("#") or stripped.upper().startswith("PENDIENTE"):
            continue
        if _DATED_ENTRY_RE.search(stripped):
            entries.append(stripped)
    return entries


def citation_author_key(citation: str) -> str:
    author_part = citation.split(",", 1)[0]
    author_part = _ET_AL_RE.sub("", author_part)
    author_part = author_part.split("&", 1)[0].split(" y ", 1)[0]
    return normalize_author_key(author_part)


def reference_author_key(entry: str) -> str:
    author_part = entry.split("(", 1)[0]
    author_part = author_part.split(",", 1)[0]
    return normalize_author_key(author_part)
