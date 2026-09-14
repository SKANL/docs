# src/docs/application/pipeline.py
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from docs.application.collection import CollectionService
from docs.application.context import ContextService
from docs.application.context_pack import ContextPackService
from docs.application.doctor import DoctorService
from docs.application.evidence import EvidenceService
from docs.application.flat_pipeline_v2 import FlatPipelineV2Adapter
from docs.application.format_audit import FormatAuditService
from docs.application.generate_visuals import GenerateVisualsService
from docs.application.ingest import IngestService
from docs.application.legacy_stage_planner import LegacyStagePlanner
from docs.application.pipeline_metadata import PipelineMetadataService
from docs.application.qa import QaService
from docs.application.review import ReviewService
from docs.application.run_history import RunHistoryService, RunRecorderService
from docs.application.section import SectionService
from docs.application.structural_audit import StructuralAuditService
from docs.domain.cover import cover_provenance
from docs.domain.models.template import Template
from docs.domain.normative import resolve_normative_settings
from docs.domain.pipeline import pipeline_stage_plan
from docs.domain.ports.context_repository import ContextRepository
from docs.domain.ports.document_renderer_port import DocumentRendererPort
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.source_repository import SourceRepository
from docs.domain.review import Issue, ReviewResult
from docs.domain.rules import review_rules
from docs.domain.workspace import Workspace


class PipelineService:
    def __init__(
        self,
        doctor_service: DoctorService,
        evidence_service: EvidenceService,
        evidence_repository: EvidenceRepository,
        collection_service: CollectionService,
        source_repository: SourceRepository,
        review_service: ReviewService,
        context_pack_service: ContextPackService,
        context_repository: ContextRepository,
        docx_assembly_service: DocumentRendererPort,
        format_audit_service: FormatAuditService,
        qa_service: QaService,
        workspace: Workspace,
        ingest_service: IngestService,
        context_service: ContextService,
        generate_visuals_service: GenerateVisualsService | None = None,
        structural_audit_service: StructuralAuditService | None = None,
        section_service: SectionService | None = None,
        run_recorder: RunRecorderService | None = None,
        metadata_service: PipelineMetadataService | None = None,
        stage_planner: LegacyStagePlanner | None = None,
    ) -> None:
        self.doctor_service = doctor_service
        self.evidence_service = evidence_service
        self.evidence_repository = evidence_repository
        self.collection_service = collection_service
        self.source_repository = source_repository
        self.review_service = review_service
        self.context_pack_service = context_pack_service
        self.context_repository = context_repository
        self.docx_assembly_service = docx_assembly_service
        self.format_audit_service = format_audit_service
        self.qa_service = qa_service
        self.workspace = workspace
        self.ingest_service = ingest_service
        self.context_service = context_service
        self.generate_visuals_service = generate_visuals_service
        self.structural_audit_service = structural_audit_service
        self.section_service = section_service or SectionService(review_service, evidence_service, context_repository)
        self.run_recorder = run_recorder or RunRecorderService(workspace, source_repository)
        self.run_history = RunHistoryService(workspace)
        self.metadata_service = metadata_service or PipelineMetadataService(workspace)
        self.stage_planner = stage_planner or LegacyStagePlanner()

    def log_run(
        self, doc_id: str, config: dict[str, Any], repo_root: Path, command: str, payload: dict[str, Any]
    ) -> Path:
        # Preserve the legacy mutability of ``source_repository`` for callers
        # that replace it after construction (notably focused test doubles).
        self.run_recorder.source_repository = self.source_repository
        return self.run_recorder.record(doc_id, config, repo_root, command, payload)

    def list_runs(self, doc_id: str, config: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
        return self.run_history.list_runs(doc_id, config, limit)

    def _next_build_version(self, doc_id: str, config: dict[str, Any]) -> int:
        return self.metadata_service.next_build_version(doc_id, config)

    def rules_manifest_state(self, config: dict[str, Any]) -> tuple[bool, int]:
        rules_path = Path(config["paths"]["rules_manifest"])
        exists = self.evidence_repository.file_exists(rules_path)
        size = self.evidence_repository.file_size(rules_path) if exists else 0
        return exists, size

    def context_confirmed_lines(self, doc_id: str, template: Template) -> list[str]:
        """Compatibility projection delegated to the named context service."""
        return self.context_service.confirmed_lines(doc_id, template)

    def build_section(self, doc_id: str, template: Template, section_id: str, config: dict[str, Any]) -> Path:
        return self.section_service.build_section(doc_id, template, section_id, config)

    def _resolve_draft_docx_name(self, doc_id: str, config: dict[str, Any]) -> str:
        return self.metadata_service.resolve_draft_docx_name(doc_id, config)

    def _stage_callables(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        repo_root: Path,
        strict: bool,
        renderer: DocumentRendererPort,
    ) -> dict[str, Callable[[], tuple[bool, str]]]:
        """Compatibility bridge for callers that inspect legacy stages."""
        return self.stage_planner.plan(self, doc_id, template, config, repo_root, strict, renderer)

    def run_pipeline(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        stage_set: str,
        repo_root: Path,
        strict: bool = False,
        renderer: DocumentRendererPort | None = None,
    ) -> dict[str, Any]:
        # `renderer` should be resolved by the composition root via
        # `Deps.resolve_renderer(config)` (format-registry resolution) and
        # passed in here; falling back to the constructor-injected renderer
        # only preserves compatibility for callers that build PipelineService
        # directly without going through the CLI composition root.
        renderer = renderer or self.docx_assembly_service
        stages = pipeline_stage_plan(stage_set, renderer.stage_plan())
        callables = self._stage_callables(doc_id, template, config, repo_root, strict, renderer)
        summary = FlatPipelineV2Adapter(operations=callables).run(
            stage_set,
            strict=strict,
            stages=tuple(stages),
        )
        cover = cover_provenance(config)
        if cover is not None:
            summary["cover"] = cover
        if stage_set in ("assemble", "all"):
            summary["build_version"] = self._next_build_version(doc_id, config)
        self.log_run(doc_id, config, repo_root, f"pipeline-{stage_set}", summary)
        return summary

    def verify_all(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        docx_path: Path | None = None,
        strict: bool = True,
    ) -> ReviewResult:
        issues: list[Issue] = []
        manifest_exists, manifest_size = self.rules_manifest_state(config)
        issues.extend(review_rules(template, manifest_exists, manifest_size, strict=strict).issues)
        normative = resolve_normative_settings(config)
        issues.extend(
            self.review_service.review_document(
                doc_id, template, strict=strict,
                manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
            ).issues
        )
        if docx_path is None:
            candidate = Path(config["paths"]["output_draft_dir"]) / self._resolve_draft_docx_name(doc_id, config)
            docx_path = candidate if candidate.exists() else None
        if docx_path and docx_path.exists():
            issues.extend(self.format_audit_service.audit_format(docx_path, config, strict=strict).issues)
            try:
                qa_dir = self.qa_service.qa_docx(config, docx_path, strict=strict)
            except Exception as exc:
                issues.append(Issue("error", f"QA visual falló: {exc}", code="qa.failed"))
            else:
                # Draft degrades when LibreOffice is absent (the format audit
                # above still ran). Degraded is not the same as failed -- but it
                # is never silent either, or `verify` would report a clean visual
                # QA that never happened.
                if not any(qa_dir.glob("*.pdf")):
                    issues.append(
                        Issue(
                            "warning",
                            "QA visual omitido: LibreOffice no está disponible (auditoría de formato sí se ejecutó).",
                            code="qa.skipped",
                        )
                    )
        return ReviewResult(issues)
