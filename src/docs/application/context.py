from __future__ import annotations

from pathlib import Path

from docs.domain.context import TopicStatus, is_prose_topic, missing_fields
from docs.domain.models.template import Template, Topic
from docs.domain.ports.context_repository import ContextRepository
from docs.domain.ports.document_repository import DocumentNotFoundError, DocumentRepository


class ContextService:
    def __init__(self, context_repo: ContextRepository, document_repo: DocumentRepository) -> None:
        self.context_repo = context_repo
        self.document_repo = document_repo

    def _require_document(self, doc_id: str) -> None:
        if not self.document_repo.exists(doc_id):
            raise DocumentNotFoundError(f"Document `{doc_id}` does not exist.")

    @staticmethod
    def _find_topic(template: Template, topic_id: str) -> Topic:
        for topic in template.context_schema.topics:
            if topic.id == topic_id:
                return topic
        raise ValueError(f"Unknown topic: {topic_id}.")

    def status(self, doc_id: str, template: Template) -> list[TopicStatus]:
        self._require_document(doc_id)
        statuses = []
        for topic in template.context_schema.topics:
            exists = self.context_repo.topic_exists(doc_id, topic.id)
            answer = self.context_repo.read_topic(doc_id, topic)
            statuses.append(
                TopicStatus(
                    id=topic.id,
                    title=topic.title,
                    required=topic.required,
                    exists=exists,
                    missing=missing_fields(topic, answer),
                )
            )
        return statuses

    def set(self, doc_id: str, template: Template, topic_id: str, value: str, field: str = "") -> Path:
        self._require_document(doc_id)
        topic = self._find_topic(template, topic_id)

        if is_prose_topic(topic):
            written_value: str | dict[str, str] = value
        else:
            known_keys = {f.key for f in topic.fields}
            if field not in known_keys:
                raise ValueError(f"Unknown field `{field}` for topic `{topic_id}`.")
            current = self.context_repo.read_topic(doc_id, topic)
            merged = dict(current) if isinstance(current, dict) else {}
            merged[field] = value
            written_value = merged

        path = self.context_repo.write_topic(doc_id, topic, written_value)
        self.context_repo.regenerate_index(doc_id, template.context_schema, self.status(doc_id, template))
        return path

    def show(self, doc_id: str, topic_id: str) -> str:
        # Legacy quirk: show does NOT validate the topic id against the schema;
        # it reads the raw file by id. read_topic_raw raises FileNotFoundError if absent.
        return self.context_repo.read_topic_raw(doc_id, topic_id)

    def remove(self, doc_id: str, template: Template, topic_id: str) -> None:
        self._require_document(doc_id)
        self.context_repo.remove_topic(doc_id, topic_id)
        self.context_repo.regenerate_index(doc_id, template.context_schema, self.status(doc_id, template))
