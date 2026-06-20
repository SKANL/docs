from __future__ import annotations

import re

from docs.domain.context import is_prose_topic
from docs.domain.models.template import Topic

_FIELD_TABLE_HEADER = "| Campo | Información |"
_FIELD_TABLE_DIVIDER = "| :---- | :---- |"
_NOISE_RE = re.compile(r"[\\*`]")
_WHITESPACE_RE = re.compile(r"\s+")


def render_topic(topic: Topic, values: str | dict[str, str] | None) -> str:
    if is_prose_topic(topic):
        body = values.strip() if isinstance(values, str) else ""
        return f"# {topic.title}\n\n{body}\n"

    data = values if isinstance(values, dict) else {}
    lines = [f"**{topic.title}**", "", _FIELD_TABLE_HEADER, _FIELD_TABLE_DIVIDER]
    for f in topic.fields:
        value = data.get(f.key, "")
        lines.append(f"| **{f.label}** | {value} |")
    return "\n".join(lines) + "\n"


def parse_topic(topic: Topic, text: str) -> str | dict[str, str]:
    if is_prose_topic(topic):
        if not text:
            return ""
        lines = text.split("\n")
        body = "\n".join(lines[1:]) if lines and lines[0].startswith("#") else text
        return body.strip()

    return {f.key: _extract_field_cell(text, f.label) for f in topic.fields}


def _extract_field_cell(text: str, label: str) -> str:
    if not text:
        return ""
    pattern = re.compile(
        r"\|\s*\*\*" + re.escape(label) + r"\*\*\s*\|\s*(.*?)\s*\|",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return ""
    return _clean_markdown(match.group(1))


def _clean_markdown(text: str) -> str:
    cleaned = _NOISE_RE.sub("", text)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip(" \t\r\n|")
