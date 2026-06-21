# src/docs/application/review.py
from __future__ import annotations

import hashlib
from pathlib import Path

from docs.domain.models.template import SectionContract, Template
from docs.domain.ports.section_repository import SectionRepository
from docs.domain.review import Issue, ReviewResult
from docs.domain.rules import review_cross_consistency, review_rules, review_section_text
from docs.domain.sections import (
    apply_stamp,
    generated_metadata_changed,
    infer_section_id_from_path,
    with_frontmatter,
)

_REQUIRED_FLOW_TERMS = ["problema", "objetivo", "metodología", "resultados", "conclusiones"]


class ReviewService:
    def __init__(self, repository: SectionRepository) -> None:
        self.repository = repository

    def review_document(
        self,
        doc_id: str,
        template: Template,
        strict: bool = False,
        *,
        manifest_exists: bool,
        manifest_size: int,
        excluded_terms: dict[str, str],
        is_policy_file: bool,
        first_person_patterns: list[str],
        subjective_terms: list[str],
        secret_patterns: list[str],
        scope_term: str = "",
        scope_focus: str = "",
    ) -> ReviewResult:
        issues: list[Issue] = list(
            review_rules(template, manifest_exists, manifest_size, strict=strict).issues
        )

        section_bodies: dict[str, str] = {}
        combined_body: list[str] = []

        for section in sorted(template.sections, key=lambda item: item.order):
            exists = self.repository.section_exists(doc_id, section.order, section.id)
            if section.required and not exists:
                issues.append(
                    Issue(
                        "error",
                        f"Sección requerida faltante: `{section.id}`.",
                        code="structure.missing_section",
                    )
                )
            elif exists:
                metadata, body = self.repository.read_section(doc_id, section.order, section.id)
                combined_body.append(body)
                section_bodies[section.id] = body

                section_path = self.repository.section_path(doc_id, section.order, section.id)
                section_id = metadata.get("section_id") or infer_section_id_from_path(section_path)
                contract = template.section_contracts.get(section_id, SectionContract())

                section_issues = review_section_text(
                    body,
                    metadata,
                    section_id,
                    contract,
                    template,
                    strict,
                    excluded_terms=excluded_terms,
                    is_policy_file=is_policy_file,
                    first_person_patterns=first_person_patterns,
                    subjective_terms=subjective_terms,
                    secret_patterns=secret_patterns,
                    scope_term=scope_term,
                    scope_focus=scope_focus,
                )
                for issue in section_issues:
                    issues.append(
                        Issue(issue.severity, f"{section_path.name}: {issue.message}", code=issue.code)
                    )

        if not self.repository.sections_dir_exists(doc_id):
            sections_dir = self.repository.section_path(doc_id, 0, "").parent
            issues.append(
                Issue(
                    "error",
                    f"No existe directorio de secciones: {sections_dir}",
                    code="structure.missing_sections_dir",
                )
            )

        combined = "\n\n".join(combined_body)
        if strict and "PENDIENTE" in combined:
            issues.append(
                Issue(
                    "error",
                    "El documento contiene PENDIENTE en modo estricto.",
                    code="content.pending_not_allowed",
                )
            )

        if strict:
            missing_flow = [term for term in _REQUIRED_FLOW_TERMS if term not in combined.lower()]
            if missing_flow:
                issues.append(
                    Issue(
                        "error",
                        "No se detecta coherencia global mínima; faltan términos de flujo: "
                        f"{', '.join(missing_flow)}.",
                        code="coherence.missing_flow",
                    )
                )

        issues.extend(
            review_cross_consistency(template, section_bodies, strict=strict).issues
        )

        return ReviewResult(issues)

    def stamp_section(
        self,
        doc_id: str,
        template: Template,
        section_id: str,
        authored_by: str,
        model: str = "",
        *,
        now: str,
    ) -> Path:
        section = next(s for s in template.sections if s.id == section_id)
        if not self.repository.section_exists(doc_id, section.order, section.id):
            path = self.repository.section_path(doc_id, section.order, section.id)
            raise FileNotFoundError(f"No existe la sección a sellar: {path}")

        metadata, body = self.repository.read_section(doc_id, section.order, section.id)
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        new_metadata = apply_stamp(metadata, section.id, section.title, body, body_hash, authored_by, model, now)
        raw_text = with_frontmatter(body, new_metadata)
        self.repository.write_section(doc_id, section.order, section.id, raw_text)
        return self.repository.section_path(doc_id, section.order, section.id)

    def build_section(
        self,
        doc_id: str,
        template: Template,
        section_id: str,
        body: str,
        *,
        source_hash: str,
        source_manifest_hash: str,
        code_evidence_manifest_hash: str,
        rules_hash: str,
        contract_hash: str,
        prompt_hash: str,
    ) -> Path:
        section = next(s for s in template.sections if s.id == section_id)
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        metadata = {
            "managed_by": "tesina-harness",
            "authored_by": "harness-scaffold",
            "schema": 3,
            "section_id": section_id,
            "title": section.title,
            "source_hash": source_hash,
            "source_manifest_hash": source_manifest_hash,
            "code_evidence_manifest_hash": code_evidence_manifest_hash,
            "rules_hash": rules_hash,
            "contract_hash": contract_hash,
            "prompt_hash": prompt_hash,
            "body_hash": body_hash,
            "last_review_hash": "",
        }
        generated = with_frontmatter(body, metadata)
        section_path = self.repository.section_path(doc_id, section.order, section.id)

        if self.repository.section_exists(doc_id, section.order, section.id):
            current_metadata, current_body = self.repository.read_section(doc_id, section.order, section.id)
            if not current_metadata and current_body == body:
                self.repository.write_section(doc_id, section.order, section.id, generated)
                return section_path
            is_managed = current_metadata.get("managed_by") == "tesina-harness"
            current_body_hash = hashlib.sha256(current_body.encode("utf-8")).hexdigest()
            is_unchanged = current_metadata.get("body_hash") == current_body_hash
            if is_managed and is_unchanged:
                if generated_metadata_changed(current_metadata, metadata):
                    self.repository.write_section(doc_id, section.order, section.id, generated)
                return section_path

            return self.repository.write_proposal_section(doc_id, section.order, section.id, generated)

        self.repository.write_section(doc_id, section.order, section.id, generated)
        return section_path

    def resolve_section_path(self, doc_id: str, template: Template, section_or_id: str) -> Path:
        for section in template.sections:
            if section.id == section_or_id:
                return self.repository.section_path(doc_id, section.order, section.id)
        raise FileNotFoundError(f"No existe sección: {section_or_id}")
