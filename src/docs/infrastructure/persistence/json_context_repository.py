from __future__ import annotations

import json
from pathlib import Path

from docs.domain.context import TopicStatus
from docs.domain.models.template import ContextSchema, Topic
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.context_markdown import parse_topic, render_topic


class JsonContextRepository:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def _context_dir(self, doc_id: str) -> Path:
        return self.workspace.doc_root(doc_id) / "context"

    def _topic_path(self, doc_id: str, topic_id: str) -> Path:
        return self._context_dir(doc_id) / f"{topic_id}.md"

    def read_topic(self, doc_id: str, topic: Topic) -> str | dict[str, str]:
        path = self._topic_path(doc_id, topic.id)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return parse_topic(topic, text)

    def read_topic_raw(self, doc_id: str, topic_id: str) -> str:
        path = self._topic_path(doc_id, topic_id)
        if not path.exists():
            raise FileNotFoundError(f"Context file for topic `{topic_id}` does not exist ({path}).")
        return path.read_text(encoding="utf-8")

    def write_topic(self, doc_id: str, topic: Topic, values: str | dict[str, str]) -> Path:
        path = self._topic_path(doc_id, topic.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_topic(topic, values), encoding="utf-8")
        return path

    def topic_exists(self, doc_id: str, topic_id: str) -> bool:
        return self._topic_path(doc_id, topic_id).exists()

    def remove_topic(self, doc_id: str, topic_id: str) -> None:
        path = self._topic_path(doc_id, topic_id)
        if path.exists():
            path.unlink()

    def regenerate_index(
        self, doc_id: str, schema: ContextSchema, statuses: list[TopicStatus]
    ) -> Path:
        context_dir = self._context_dir(doc_id)
        context_dir.mkdir(parents=True, exist_ok=True)
        topics_by_id = {t.id: t for t in schema.topics}

        topic_entries = []
        by_section: dict[str, list[str]] = {}
        for status in statuses:
            topic = topics_by_id[status.id]
            topic_entries.append({
                "id": status.id,
                "title": status.title,
                "file": f"{status.id}.md",
                "consumed_by": list(topic.consumed_by),
                "complete": status.complete,
            })
            for section_id in topic.consumed_by:
                by_section.setdefault(section_id, []).append(status.id)

        index = {"schema": 1, "topics": topic_entries, "by_section": by_section}
        json_path = context_dir / "index.json"
        json_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        md_lines = ["| Tema | Archivo | Completo | Consumido por |", "| :---- | :---- | :---- | :---- |"]
        for status in statuses:
            topic = topics_by_id[status.id]
            complete = "sí" if status.complete else "no"
            consumed = ", ".join(topic.consumed_by) or "—"
            md_lines.append(f"| {status.title} | {status.id}.md | {complete} | {consumed} |")
        md_path = context_dir / "index.md"
        md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

        return json_path

    def _requests_path(self, doc_id: str) -> Path:
        return self._context_dir(doc_id) / "_requests.md"

    def read_requests(self, doc_id: str) -> str:
        path = self._requests_path(doc_id)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def write_requests(self, doc_id: str, text: str) -> Path:
        path = self._requests_path(doc_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path
