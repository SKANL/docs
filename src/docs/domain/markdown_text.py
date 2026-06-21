# src/docs/domain/markdown_text.py
from __future__ import annotations

import json
import re

_ACCENT_TRANSLATION = str.maketrans("ÁÉÍÓÚÜÑáéíóúüñ", "AEIOUUNaeiouun")

_BOLD_RE = re.compile(r"\*\*(.*?)\*\*")
_ITALIC_RE = re.compile(r"\*(.*?)\*")
_CODE_RE = re.compile(r"`(.*?)`")
_WHITESPACE_RE = re.compile(r"\s+")

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_STRUCTURE_RE = re.compile(r"[*_#>|-]+")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def split_frontmatter(raw_text: str) -> tuple[dict, str]:
    if not raw_text.startswith("---\n"):
        return {}, raw_text
    end = raw_text.find("\n---\n", 4)
    if end == -1:
        return {}, raw_text
    raw = raw_text[4:end].strip()
    body = raw_text[end + 5:]
    try:
        return json.loads(raw), body
    except json.JSONDecodeError:
        return {}, raw_text


def clean_markdown_text(text: str) -> str:
    text = text.replace("\\", "")
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    text = _CODE_RE.sub(r"\1", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip(" \t\r\n|")


def strip_frontmatter_and_markdown(text: str) -> str:
    _metadata, body = split_frontmatter(text)
    body = _FENCED_CODE_RE.sub(" ", body)
    body = _INLINE_CODE_RE.sub(r"\1", body)
    body = _IMAGE_RE.sub(" ", body)
    body = _LINK_RE.sub(" ", body)
    body = _STRUCTURE_RE.sub(" ", body)
    return body


def extract_markdown_headings(text: str) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            headings.append(clean_markdown_text(match.group(2)))
    return headings


def normalize_heading(text: str) -> str:
    return text.translate(_ACCENT_TRANSLATION).upper().strip()


def normalize_author_key(value: str) -> str:
    value = normalize_heading(value).lower()
    value = _NON_ALNUM_RE.sub(" ", value)
    return value.strip()


def normalize_for_sort(value: str) -> str:
    return normalize_author_key(value) or value.lower()


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = _WHITESPACE_RE.sub(" ", value).strip()
        if normalized and normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out
