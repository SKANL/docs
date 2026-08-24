# tests/integration/test_technical_report_srs_acceptance.py
"""PR5 (item D) falsifiable acceptance gate: `technical-report-srs` -- a
second built-in template, structurally different from both existing ones
(no APA, English, technical-report/SRS section shape, its OWN
`contested_stack_terms` list) -- MUST pass `review-rules`/`build-rules`/
`doctor` and a full `pipeline all` run with zero blocking errors, AND its
review outcome must reflect ITS OWN declared rule config, not estadia's.
Modeled directly on `test_documento_generico_acceptance.py` (spec:
template-provisioning "Second Built-In Non-APA Template")."""
from __future__ import annotations

import json
from pathlib import Path

from docs.application.asset import AssetService
from docs.application.doctor import DoctorService
from docs.application.evidence import EvidenceService
from docs.application.review import ReviewService
from docs.domain.models.template import Template
from docs.domain.normative import resolve_normative_settings
from docs.domain.rules import review_rules
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "templates" / "technical-report-srs.json"


def _resolved_config(tmp_path: Path) -> dict:
    """Mirrors `Deps.resolve_context`'s shape: the template's own declared
    `paths` merged with computed, always-present per-document paths."""
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    paths = dict(raw.get("paths", {}))
    paths.update(
        {
            "rules_manifest": str(sections_dir / "manual-rules.json"),
            "context_dir": str(tmp_path / "context"),
        }
    )
    raw["paths"] = paths
    return raw


def test_technical_report_srs_review_rules_passes_with_zero_errors(tmp_path: Path):
    config = _resolved_config(tmp_path)
    template = Template.model_validate(config)

    result = review_rules(template, manifest_exists=True, manifest_size=42, strict=False)

    assert result.issues == []
    assert result.passed is True


def test_technical_report_srs_build_rules_succeeds_with_zero_errors(tmp_path: Path):
    config = _resolved_config(tmp_path)
    service = EvidenceService(JsonEvidenceRepository())

    manifest_path = service.build_rules(config)

    assert manifest_path.exists()


def test_technical_report_srs_doctor_rules_config_check_passes(tmp_path: Path, monkeypatch):
    # Toolchain checks (pandoc/libreoffice/gh) are host-environment concerns,
    # orthogonal to this template's rule-config scope -- patched the same way
    # test_documento_generico_acceptance.py does.
    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_pandoc_executable", lambda paths: "pandoc"
    )
    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_libreoffice_executable", lambda paths: "soffice"
    )
    monkeypatch.setattr("shutil.which", lambda name: "gh")

    config = _resolved_config(tmp_path)
    Path(config["paths"]["context_dir"]).mkdir(exist_ok=True)
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    evidence_repo = JsonEvidenceRepository()
    evidence_service = EvidenceService(evidence_repo)
    evidence_service.build_rules(config)
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    tool_resolver = SystemToolResolverAdapter()
    doctor_service = DoctorService(evidence_repo, asset_service, tool_resolver)

    result = doctor_service.run_doctor("srs-doc", config, strict=False)

    rules_check = next(c for c in result.checks if c.name == "rules_config")
    assert rules_check.ok is True, rules_check.detail


def test_technical_report_srs_full_pipeline_all_passes_with_zero_errors(tmp_path: Path, monkeypatch):
    """The end-to-end gate: `pipeline all` (prep -> review-document ->
    build-docx -> format-audit-docx -> qa-docx) completes green for a
    freshly-scaffolded document using this template -- proving item A's
    template-driven rules generalize past estadia through a REAL docx
    build, not just a rules-config unit check."""
    from docs.application.collection import CollectionService
    from docs.application.context import ContextService
    from docs.application.context_pack import ContextPackService
    from docs.application.docx_assembly import DocxRendererAdapter
    from docs.application.format_audit import FormatAuditService
    from docs.application.ingest import IngestService
    from docs.application.pipeline import PipelineService
    from docs.application.qa import QaService
    from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter
    from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
    from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter
    from docs.infrastructure.ingest.filetype_detector_adapter import FiletypeDetectorAdapter
    from docs.infrastructure.persistence.context_markdown import ContextMarkdownAdapter
    from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository
    from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
    from docs.infrastructure.persistence.json_repository import JsonDocumentRepository

    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_pandoc_executable", lambda paths: "pandoc"
    )
    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_libreoffice_executable", lambda paths: "soffice"
    )
    # `shutil.which` stays REAL and unmocked here: doctor's "uv" check is
    # `required=True` unconditionally (the harness runs under `uv run ...`),
    # so faking it absent would fail-fast doctor before build-sections ever
    # runs. "soffice" genuinely isn't installed on this host -- real absence
    # is exactly what proves qa-docx's graceful degrade (draft mode), so it
    # must stay real too, never faked present.

    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    Path(tmp_path / "documents" / "doc1").mkdir(parents=True)
    Path(tmp_path / "context").mkdir()
    # `JsonSectionRepository` always writes under `workspace.doc_root(doc_id)
    # / "sections"` (workspace-derived, not `config["paths"]["sections_dir"]`)
    # -- `resolve_existing_section_paths` (build-docx) reads the CONFIGURED
    # path, so the two must agree for a real assemble to find any sections.
    sections_dir = workspace.doc_root("doc1") / "sections"

    config = _resolved_config(tmp_path)
    draft_dir = tmp_path / "draft"
    config["paths"].update(
        {
            "sections_dir": str(sections_dir),
            "source_manifest": str(tmp_path / "source.json"),
            "issues_manifest": str(tmp_path / "issues.json"),
            "code_evidence_manifest": str(tmp_path / "code-evidence.json"),
            "fact_ledger": str(tmp_path / "00-fact-ledger.md"),
            "prompts_dir": str(tmp_path / "prompts"),
            "output_draft_dir": str(draft_dir),
            "output_qa_dir": str(tmp_path / "qa"),
        }
    )
    template = Template.model_validate(config)

    evidence_repo = JsonEvidenceRepository()
    section_repo = JsonSectionRepository(workspace)
    source_repo = FilesystemSourceRepository()
    context_repo = JsonContextRepository(workspace)
    document_repo = JsonDocumentRepository(workspace)
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    evidence_service = EvidenceService(evidence_repo)
    review_service = ReviewService(section_repo)
    collection_service = CollectionService(source_repo, evidence_repo)
    context_pack_service = ContextPackService(section_repo, evidence_repo, evidence_service, review_service)
    context_service = ContextService(context_repo, document_repo, ContextMarkdownAdapter())
    tool_resolver = SystemToolResolverAdapter()
    docx_assembly_service = DocxRendererAdapter(PythonDocxAssemblyAdapter(), asset_service, tool_resolver)
    format_audit_service = FormatAuditService(PythonDocxAuditAdapter())
    qa_service = QaService(LibreOfficeQaAdapter(), format_audit_service)
    doctor_service = DoctorService(evidence_repo, asset_service, tool_resolver)
    ingest_service = IngestService(FiletypeDetectorAdapter(), {})
    pipeline = PipelineService(
        doctor_service, evidence_service, evidence_repo, collection_service, source_repo,
        review_service, context_pack_service, context_repo, docx_assembly_service,
        format_audit_service, qa_service, workspace, ingest_service,
        context_service=context_service,
    )

    summary = pipeline.run_pipeline("doc1", template, config, "all", repo_root=tmp_path, strict=False)

    failed = [s for s in summary["stages"] if not s["ok"]]
    assert summary["passed"] is True, failed
    build_stage = next(s for s in summary["stages"] if s["stage"] == "build-docx")
    assert Path(build_stage["detail"]).exists()


def test_technical_report_srs_review_document_reflects_its_own_rules_not_estadias(tmp_path: Path):
    """The Scenario-2 proof (spec: template-provisioning): a section body
    mentioning a technology from THIS template's OWN `contested_stack_terms`
    (never estadia's `Laravel`/`Supabase`/`bun.js`/`MySQL`/`GCP`/`Firebase`
    list) is flagged; and no APA-related issue fires despite an unreferenced
    body, because this template declares `citation_style: none`."""
    config = _resolved_config(tmp_path)
    template = Template.model_validate(config)
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    section_repo = JsonSectionRepository(workspace)
    review_service = ReviewService(section_repo)

    for section in template.sections:
        body = f"# {section.title}\n\nThis section documents {section.id} for the project.\n"
        if section.id == "implementation":
            body = "# IMPLEMENTATION\n\nThe service layer is built on jQuery for legacy DOM glue code.\n"
        section_repo.write_section("doc1", section.order, section.id, body)

    normative = resolve_normative_settings(config)
    result = review_service.review_document(
        "doc1", template, strict=False, manifest_exists=True, manifest_size=42, normative=normative,
    )

    codes = {issue.code for issue in result.issues}
    assert "coherence.contested_stack_unqualified" in codes
    assert not any(code.startswith("apa.") for code in codes)


def test_technical_report_srs_review_document_no_duration_mismatch_for_generic_hours(tmp_path: Path):
    """Doc-type-coupling leak fix: this template does NOT declare
    `cross_consistency.duration_consistency` (only estadia's does), so a
    document legitimately mentioning two different hour figures across
    sections must NOT trigger estadia's "duración de la estadía" coherence
    check (spec: template-provisioning "No hardcoded document-type literal
    in domain code")."""
    config = _resolved_config(tmp_path)
    template = Template.model_validate(config)
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    section_repo = JsonSectionRepository(workspace)
    review_service = ReviewService(section_repo)

    for section in template.sections:
        body = f"# {section.title}\n\nThis section documents {section.id} for the project.\n"
        if section.id == "implementation":
            body = "# IMPLEMENTATION\n\nThe setup phase took 40 horas and testing took 80 horas.\n"
        section_repo.write_section("doc1", section.order, section.id, body)

    normative = resolve_normative_settings(config)
    result = review_service.review_document(
        "doc1", template, strict=False, manifest_exists=True, manifest_size=42, normative=normative,
    )

    assert not any(issue.code == "coherence.duration_mismatch" for issue in result.issues)
