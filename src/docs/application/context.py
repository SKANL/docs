from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.application.ingest import _InlineJsonWriter
from docs.domain.context import TopicStatus, is_prose_topic, missing_fields
from docs.domain.markdown_text import clean_markdown_text
from docs.domain.models.template import Template, Topic
from docs.domain.ports.context_markdown_port import ContextMarkdownPort
from docs.domain.ports.context_repository import ContextRepository
from docs.domain.ports.document_repository import DocumentNotFoundError, DocumentRepository
from docs.domain.ports.ingest_artifact_writer import IngestArtifactWriter
from docs.domain.rules import requirement_present


class ContextService:
    def __init__(
        self,
        context_repo: ContextRepository,
        document_repo: DocumentRepository,
        context_markdown: ContextMarkdownPort,
    ) -> None:
        self.context_repo = context_repo
        self.document_repo = document_repo
        self.context_markdown = context_markdown

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

    def ingest(self, doc_id: str, template: Template) -> list[str]:
        self._require_document(doc_id)
        text = self.context_repo.read_requests(doc_id)
        if not text:
            raise FileNotFoundError(f"No pending requests file for document `{doc_id}`.")

        parsed = self.context_markdown.parse_requests(template.context_schema, text)
        topics_by_id = {t.id: t for t in template.context_schema.topics}
        written: list[str] = []

        for topic_id, new_value in parsed.items():
            topic = topics_by_id.get(topic_id)
            if topic is None:
                continue

            current = self.context_repo.read_topic(doc_id, topic)

            if is_prose_topic(topic):
                new_text = new_value if isinstance(new_value, str) else ""
                merged: str = new_text.strip() if new_text.strip() else (current if isinstance(current, str) else "")
                if str(merged).strip():
                    self.context_repo.write_topic(doc_id, topic, merged)
                    written.append(topic_id)
            else:
                current_fields = current if isinstance(current, dict) else {}
                new_fields = new_value if isinstance(new_value, dict) else {}
                merged_fields = {**current_fields, **{k: v for k, v in new_fields.items() if v}}
                if any(merged_fields.values()):
                    self.context_repo.write_topic(doc_id, topic, merged_fields)
                    written.append(topic_id)

        self.context_repo.regenerate_index(doc_id, template.context_schema, self.status(doc_id, template))
        return written

    def write_requests_file(self, doc_id: str, template: Template, only_topic: str = "") -> Path:
        """Non-interactive elicitation: render the pending-fields questionnaire
        and persist it. Composes the already-migrated status + render_requests +
        ContextRepository.write_requests. The interactive TTY loop (legacy
        elicit_interactive) is out of scope for this migration."""
        self._require_document(doc_id)
        statuses = self.status(doc_id, template)
        pairs = [(s, self.context_repo.read_topic(doc_id, self._find_topic(template, s.id))) for s in statuses]
        text = self.context_markdown.render_requests(template.context_schema, pairs, only_topic=only_topic)
        return self.context_repo.write_requests(doc_id, text)

    def build_gap_report(
        self,
        doc_id: str,
        template: Template,
        section_bodies: dict[str, str],
        sections_dir: Path,
        writer: IngestArtifactWriter | None = None,
    ) -> dict[str, Any]:
        """Machine-readable gap report (design.md Decision 7, spec:
        document-pipeline "Machine-Readable Gap Report") -- combines
        context-required-field gaps (reusing `status`/`missing_fields`,
        already built) with section `required_content` gaps (reusing
        `rules.requirement_present`, already built for post-hoc review;
        here surfaced pre-emptively). No new ContextService dependency:
        `writer` defaults to the same atomic `IngestArtifactWriter`
        fallback `IngestService` uses when the composition root does not
        inject one (`cli/_shared.py`/`Deps.__init__` passes the same real
        `FilesystemIngestArtifactWriter` instance already wired to
        `IngestService`, ponytail: reuse, no new wiring)."""
        self._require_document(doc_id)
        context_gaps = [
            {"topic_id": status.id, "missing": status.missing}
            for status in self.status(doc_id, template)
            if status.missing
        ]
        section_gaps: list[dict[str, Any]] = []
        for section_id in sorted(template.section_contracts):
            contract = template.section_contracts[section_id]
            plain = clean_markdown_text(section_bodies.get(section_id, "")).lower()
            missing = [
                requirement
                for requirement in contract.required_content
                if not requirement_present(requirement, plain, contract.detect)
            ]
            if missing:
                section_gaps.append({"section_id": section_id, "missing": missing})
        report: dict[str, Any] = {
            "schema": 1,
            "context_gaps": context_gaps,
            "section_gaps": section_gaps,
        }
        (writer or _InlineJsonWriter()).write_json(Path(sections_dir) / "gap-report.json", report)
        return report
