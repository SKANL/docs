# src/docs/application/pipeline.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from docs.application.collection import CollectionService
from docs.application.context_pack import ContextPackService
from docs.application.doctor import DoctorService
from docs.application.docx_assembly import DocxAssemblyService
from docs.application.evidence import EvidenceService
from docs.application.format_audit import FormatAuditService
from docs.application.qa import QaService
from docs.application.review import ReviewService
from docs.domain.models.template import Template
from docs.domain.normative import resolve_normative_settings
from docs.domain.pipeline import pipeline_stage_plan
from docs.domain.ports.context_repository import ContextRepository
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.source_repository import SourceRepository
from docs.domain.review import Issue, ReviewResult
from docs.domain.rules import review_rules
from docs.domain.workspace import Workspace

_DRAFT_DOCX_NAME = "tesina-draft.docx"


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
        docx_assembly_service: DocxAssemblyService,
        format_audit_service: FormatAuditService,
        qa_service: QaService,
        workspace: Workspace,
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

    def log_run(
        self, doc_id: str, config: dict[str, Any], repo_root: Path, command: str, payload: dict[str, Any]
    ) -> Path:
        runs_dir = self._runs_dir(doc_id, config)
        runs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="microseconds")
        record = {
            "timestamp": timestamp,
            "command": command,
            "git_commit": self.source_repository.run_git_rev_parse_head(repo_root),
            **payload,
        }
        safe_name = timestamp.replace(":", "-")
        path = runs_dir / f"{safe_name}-{command}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def list_runs(self, doc_id: str, config: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
        runs_dir = self._runs_dir(doc_id, config)
        if not runs_dir.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(runs_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return records

    def _runs_dir(self, doc_id: str, config: dict[str, Any]) -> Path:
        configured = config.get("paths", {}).get("runs_dir")
        if configured:
            return Path(configured)
        return self.workspace.doc_root(doc_id) / "runs"

    def _rules_manifest_state(self, config: dict[str, Any]) -> tuple[bool, int]:
        rules_path = Path(config["paths"]["rules_manifest"])
        exists = self.evidence_repository.file_exists(rules_path)
        size = self.evidence_repository.file_size(rules_path) if exists else 0
        return exists, size

    def _context_confirmed_lines(self, doc_id: str, template: Template) -> list[str]:
        # Legacy also routes sensitive topic fields into a separate
        # "dato_sensible" ledger bucket. EvidenceService.render_fact_ledger
        # (Slice 8) only accepts one confirmado-scoped list, so sensitive
        # fields are skipped here rather than mis-classified. See the plan's
        # "Risks and open judgment calls" (Judgment call 4).
        lines: list[str] = []
        for topic in template.context_schema.topics:
            values = self.context_repository.read_topic(doc_id, topic)
            if isinstance(values, dict):
                for field in topic.fields:
                    value = values.get(field.key, "")
                    if not value or field.sensitive:
                        continue
                    lines.append(f"{field.label}: {value}")
            elif isinstance(values, str) and values.strip():
                snippet = values.strip()[:160]
                lines.append(f"{topic.title or topic.id}: {snippet}")
        return lines

    def _stage_callables(
        self, doc_id: str, template: Template, config: dict[str, Any], repo_root: Path, strict: bool
    ) -> dict[str, Callable[[], tuple[bool, str]]]:
        def stage_doctor() -> tuple[bool, str]:
            result = self.doctor_service.run_doctor(doc_id, config, strict=strict)
            return result.passed, result.to_markdown()

        def stage_build_rules() -> tuple[bool, str]:
            return True, str(self.evidence_service.build_rules(config))

        def stage_review_rules() -> tuple[bool, str]:
            manifest_exists, manifest_size = self._rules_manifest_state(config)
            result = review_rules(template, manifest_exists, manifest_size, strict=strict)
            return result.passed, result.to_markdown()

        def stage_collect_sources() -> tuple[bool, str]:
            return True, str(self.collection_service.collect_sources(config))

        def stage_collect_code_evidence() -> tuple[bool, str]:
            return True, str(self.collection_service.collect_code_evidence(config, repo_root))

        def stage_collect_issues() -> tuple[bool, str]:
            try:
                return True, str(self.collection_service.collect_issues(config, repo_root))
            except Exception as exc:  # best-effort: gh puede no estar disponible
                return True, f"omitido: {exc}"

        def stage_build_ledger() -> tuple[bool, str]:
            path = Path(config["paths"]["fact_ledger"])
            path.parent.mkdir(parents=True, exist_ok=True)
            context_lines = self._context_confirmed_lines(doc_id, template)
            path.write_text(self.evidence_service.render_fact_ledger(config, context_lines), encoding="utf-8")
            return True, str(path)

        def stage_build_sections() -> tuple[bool, str]:
            raise NotImplementedError(
                "build-section requiere un renderer de borradores y source_hash/"
                "prompt_hash aún no modelados en esta migración (ver Slice 6 y "
                "Slice 8, Design Decision 4)."
            )

        def stage_pack_context() -> tuple[bool, str]:
            normative = resolve_normative_settings(config)
            manifest_exists, manifest_size = self._rules_manifest_state(config)
            paths = [
                str(self.context_pack_service.pack_context(doc_id, template, section.id, config, **normative))
                for section in template.sections
            ]
            self.context_pack_service.pack_context_document(
                doc_id, template, config,
                manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
            )
            return True, f"{len(paths)} context packs + 1 documento"

        def stage_review_document() -> tuple[bool, str]:
            normative = resolve_normative_settings(config)
            manifest_exists, manifest_size = self._rules_manifest_state(config)
            result = self.review_service.review_document(
                doc_id, template, strict=strict,
                manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
            )
            return result.passed, result.to_markdown()

        def stage_build_docx() -> tuple[bool, str]:
            return True, str(self.docx_assembly_service.build(doc_id, config))

        def stage_format_audit() -> tuple[bool, str]:
            docx_path = Path(config["paths"]["output_draft_dir"]) / _DRAFT_DOCX_NAME
            result = self.format_audit_service.audit_format(docx_path, config, strict=strict)
            return result.passed, result.to_markdown()

        def stage_qa_docx() -> tuple[bool, str]:
            docx_path = Path(config["paths"]["output_draft_dir"]) / _DRAFT_DOCX_NAME
            return True, str(self.qa_service.qa_docx(config, docx_path, strict=strict))

        return {
            "doctor": stage_doctor,
            "build-rules": stage_build_rules,
            "review-rules": stage_review_rules,
            "collect-sources": stage_collect_sources,
            "collect-code-evidence": stage_collect_code_evidence,
            "collect-issues": stage_collect_issues,
            "build-ledger": stage_build_ledger,
            "build-sections": stage_build_sections,
            "pack-context": stage_pack_context,
            "review-document": stage_review_document,
            "build-docx": stage_build_docx,
            "format-audit-docx": stage_format_audit,
            "qa-docx": stage_qa_docx,
        }

    def run_pipeline(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        stage_set: str,
        repo_root: Path,
        strict: bool = False,
    ) -> dict[str, Any]:
        stages = pipeline_stage_plan(stage_set)
        callables = self._stage_callables(doc_id, template, config, repo_root, strict)
        results: list[dict[str, Any]] = []
        passed = True
        for name, fail_fast in stages:
            started = datetime.now()
            try:
                ok, detail = callables[name]()
            except Exception as exc:
                ok, detail = False, f"ERROR: {exc}"
            duration = (datetime.now() - started).total_seconds()
            results.append({"stage": name, "ok": ok, "duration_s": round(duration, 3), "detail": detail})
            if not ok:
                passed = False
                if fail_fast:
                    break
        summary = {"stage_set": stage_set, "strict": strict, "passed": passed, "stages": results}
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
        manifest_exists, manifest_size = self._rules_manifest_state(config)
        issues.extend(review_rules(template, manifest_exists, manifest_size, strict=strict).issues)
        normative = resolve_normative_settings(config)
        issues.extend(
            self.review_service.review_document(
                doc_id, template, strict=strict,
                manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
            ).issues
        )
        if docx_path is None:
            candidate = Path(config["paths"]["output_draft_dir"]) / _DRAFT_DOCX_NAME
            docx_path = candidate if candidate.exists() else None
        if docx_path and docx_path.exists():
            issues.extend(self.format_audit_service.audit_format(docx_path, config, strict=strict).issues)
            try:
                self.qa_service.qa_docx(config, docx_path, strict=strict)
            except Exception as exc:
                issues.append(Issue("error", f"QA visual falló: {exc}", code="qa.failed"))
        return ReviewResult(issues)
