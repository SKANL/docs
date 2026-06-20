from __future__ import annotations

import re

from docs.domain.context import TopicStatus, is_prose_topic
from docs.domain.models.template import ContextSchema, Topic

_FIELD_TABLE_HEADER = "| Campo | Información |"
_FIELD_TABLE_DIVIDER = "| :---- | :---- |"
_NOISE_RE = re.compile(r"[\\*`]")
_WHITESPACE_RE = re.compile(r"\s+")

_REQUEST_HEADER_RE = re.compile(r"^##\s+.*\(`([^`]+)`\)\s*(\[prosa\])?\s*$", re.MULTILINE)
_REQUEST_FIELD_RE = re.compile(r"^-\s+\*\*.+?\*\*\s+\(`([^`]+)`\):\s*(.*)$", re.MULTILINE)

_NO_PENDING = "_No hay campos pendientes._"


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


def render_requests(
    schema: ContextSchema,
    statuses_with_values: list[tuple[TopicStatus, str | dict[str, str]]],
    only_topic: str = "",
) -> str:
    topics_by_id = {t.id: t for t in schema.topics}
    blocks: list[str] = []

    for status, value in statuses_with_values:
        if not status.missing:
            continue
        if only_topic and status.id != only_topic:
            continue
        topic = topics_by_id[status.id]

        if is_prose_topic(topic):
            lines = [f"## {topic.title} (`{topic.id}`) [prosa]"]
            if topic.prompt:
                lines.append(f"> {topic.prompt}")
            lines += ["", "<<<", "", ">>>"]
            blocks.append("\n".join(lines))
        else:
            data = value if isinstance(value, dict) else {}
            lines = [f"## {topic.title} (`{topic.id}`)"]
            for f in topic.fields:
                current = data.get(f.key, "")
                lines.append(f"- **{f.label}** (`{f.key}`): {current}")
            blocks.append("\n".join(lines))

    if not blocks:
        return _NO_PENDING
    return "\n\n".join(blocks) + "\n"


def parse_requests(schema: ContextSchema, text: str) -> dict[str, str | dict[str, str]]:
    known_ids = {t.id for t in schema.topics}
    headers = list(_REQUEST_HEADER_RE.finditer(text))
    result: dict[str, str | dict[str, str]] = {}

    for i, header in enumerate(headers):
        topic_id = header.group(1)
        if topic_id not in known_ids:
            continue
        start = header.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end]

        delim_match = re.search(r"<<<\s*\n(.*?)\n\s*>>>", block, re.DOTALL)
        if delim_match:
            result[topic_id] = delim_match.group(1).strip()
        else:
            fields = {m.group(1): m.group(2).strip() for m in _REQUEST_FIELD_RE.finditer(block)}
            result[topic_id] = fields

    return result
