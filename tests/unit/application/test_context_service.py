# tests/unit/application/test_context_service.py
"""Unit coverage for ContextService (document-pipeline spec: `Application-
Layer Test Coverage`). Uses lightweight fakes for the repository ports
instead of real JSON-backed adapters -- exercises status/set/unknown-topic
handling in isolation (see tests/integration/test_context_service.py for the
repository-backed integration coverage of this same service)."""
from __future__ import annotations

import pytest

from docs.application.context import ContextService
from docs.domain.models.template import ContextSchema, Field, Template, Topic


class _FakeDocumentRepo:
    def exists(self, doc_id: str) -> bool:
        return True


class _FakeContextRepo:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def topic_exists(self, doc_id: str, topic_id: str) -> bool:
        return topic_id in self.values

    def read_topic(self, doc_id: str, topic: Topic):
        return self.values.get(topic.id, {})

    def write_topic(self, doc_id: str, topic: Topic, values):
        self.values[topic.id] = values
        return f"{topic.id}.md"

    def regenerate_index(self, doc_id, schema, statuses):
        return "index.json"


def _template(topic: Topic) -> Template:
    return Template(type="doc", title="Doc", context_schema=ContextSchema(topics=[topic]))


def test_status_reports_missing_required_fields_for_a_topic_never_answered():
    topic = Topic(
        id="alumno", title="Alumno", required=True,
        fields=[Field(key="nombre", label="Nombre", required=True)],
    )
    service = ContextService(_FakeContextRepo(), _FakeDocumentRepo(), context_markdown=None)

    statuses = service.status("doc1", _template(topic))

    assert statuses[0].id == "alumno"
    assert statuses[0].missing == ["Nombre"]
    assert statuses[0].complete is False


def test_set_raises_for_an_unknown_field_on_a_field_based_topic():
    topic = Topic(id="alumno", title="Alumno", fields=[Field(key="nombre", label="Nombre")])
    service = ContextService(_FakeContextRepo(), _FakeDocumentRepo(), context_markdown=None)

    with pytest.raises(ValueError, match="Unknown field"):
        service.set("doc1", _template(topic), "alumno", "Ada", field="no-existe")


def test_set_raises_for_an_unknown_topic_id():
    topic = Topic(id="alumno", title="Alumno", fields=[Field(key="nombre", label="Nombre")])
    service = ContextService(_FakeContextRepo(), _FakeDocumentRepo(), context_markdown=None)

    with pytest.raises(ValueError, match="Unknown topic"):
        service.set("doc1", _template(topic), "no-existe", "valor")
