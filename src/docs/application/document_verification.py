from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.application.format_audit import FormatAuditService
from docs.application.output_names import resolve_draft_docx_name
from docs.application.qa import QaService
from docs.application.review import ReviewService
from docs.domain.models.template import Template
from docs.domain.normative import resolve_normative_settings
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.review import Issue, ReviewResult
from docs.domain.rules import review_rules


class DocumentVerificationService:
    """Application service for the legacy ``verify_all`` behavior."""

    def __init__(self, review_service: ReviewService, evidence_repository: EvidenceRepository,
                 format_audit_service: FormatAuditService, qa_service: QaService) -> None:
        self.review_service = review_service
        self.evidence_repository = evidence_repository
        self.format_audit_service = format_audit_service
        self.qa_service = qa_service

    def verify_all(self, doc_id: str, template: Template, config: dict[str, Any],
                   docx_path: Path | None = None, strict: bool = True) -> ReviewResult:
        issues: list[Issue] = []
        rules_path = Path(config["paths"]["rules_manifest"])
        exists = self.evidence_repository.file_exists(rules_path)
        size = self.evidence_repository.file_size(rules_path) if exists else 0
        issues.extend(review_rules(template, exists, size, strict=strict).issues)
        issues.extend(self.review_service.review_document(
            doc_id, template, strict=strict, manifest_exists=exists,
            manifest_size=size, normative=resolve_normative_settings(config),
        ).issues)
        if docx_path is None:
            candidate = Path(config["paths"]["output_draft_dir"]) / resolve_draft_docx_name(doc_id, config)
            docx_path = candidate if candidate.exists() else None
        if docx_path and docx_path.exists():
            issues.extend(self.format_audit_service.audit_format(docx_path, config, strict=strict).issues)
            try:
                qa_dir = self.qa_service.qa_docx(config, docx_path, strict=strict)
            except Exception as exc:
                issues.append(Issue("error", f"QA visual falló: {exc}", code="qa.failed"))
            else:
                if not any(qa_dir.glob("*.pdf")):
                    issues.append(Issue("warning", "QA visual omitido: LibreOffice no está disponible (auditoría de formato sí se ejecutó).", code="qa.skipped"))
        return ReviewResult(issues)
