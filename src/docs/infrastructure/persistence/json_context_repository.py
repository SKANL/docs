from __future__ import annotations

from pathlib import Path

from docs.domain.models.template import Topic
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
