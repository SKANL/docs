from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.application.evidence import EvidenceService
from docs.application.review import ReviewService
from docs.domain.models.template import SectionContract, Template
from docs.domain.normative import resolve_normative_settings
from docs.domain.ports.context_repository import ContextRepository
from docs.domain.section_rendering import render_section_draft


class SectionService:
    """Application service for creating section scaffolds."""

    def __init__(
        self,
        review_service: ReviewService,
        evidence_service: EvidenceService,
        context_repository: ContextRepository,
    ) -> None:
        self.review_service = review_service
        self.evidence_service = evidence_service
        self.context_repository = context_repository

    def build_section(self, doc_id: str, template: Template, section_id: str, config: dict[str, Any]) -> Path:
        section = next((s for s in template.sections if s.id == section_id), None)
        if section is None:
            raise FileNotFoundError(f"No existe sección: {section_id}")
        contract = template.section_contracts.get(section_id, SectionContract())
        context: dict[str, str] = {}
        for topic in template.context_schema.topics:
            if section_id not in topic.consumed_by:
                continue
            if self.context_repository.topic_exists(doc_id, topic.id):
                context[topic.id] = self.context_repository.read_topic_raw(doc_id, topic.id)
        keyword_bold_terms = config.get("format", {}).get("keyword_bold_terms", {}).get(section_id, [])
        citation_style = resolve_normative_settings(config).citation_style
        body = render_section_draft(section_id, section.title, contract, context, keyword_bold_terms, citation_style)
        return self.review_service.build_section(
            doc_id, template, section_id, body,
            source_hash=self.evidence_service.source_hash(config),
            source_manifest_hash=self.evidence_service.manifest_hash(config["paths"].get("source_manifest")),
            code_evidence_manifest_hash=self.evidence_service.manifest_hash(
                config["paths"].get("code_evidence_manifest")
            ),
            rules_hash=self.evidence_service.rules_hash(config),
            contract_hash=self.evidence_service.contract_hash(config, section_id),
            prompt_hash=self.evidence_service.prompt_hash(config),
        )
