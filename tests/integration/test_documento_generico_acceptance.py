# tests/integration/test_documento_generico_acceptance.py
"""Front A falsifiable acceptance gate (universal-schema-harness proposal):
`documento-generico` -- a document type that declares NONE of the estadía
optional policy blocks (no `preliminaries`, no `paths.extracted_dir`, APA
disabled, no margin `advisor_overrides`) -- MUST pass `doctor`, `review-rules`,
and `build-rules` with zero errors. Before this front, every one of those
checks was hardcoded against estadía-shaped values and would have rejected
this template unconditionally.
"""
from __future__ import annotations

import json
from pathlib import Path

from docs.application.asset import AssetService
from docs.application.doctor import DoctorService
from docs.application.evidence import EvidenceService
from docs.domain.models.template import Template
from docs.domain.rules import review_rules
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.domain.workspace import Workspace

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "templates" / "documento-generico.json"


def _resolved_config(tmp_path: Path) -> dict:
    """Mirrors the shape `Deps.resolve_context` produces: the template's own
    declared `paths` (here: `{}`) merged with computed, always-present
    per-document paths."""
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


def test_documento_generico_review_rules_passes_with_zero_errors(tmp_path: Path):
    config = _resolved_config(tmp_path)
    template = Template.model_validate(config)

    result = review_rules(template, manifest_exists=True, manifest_size=42, strict=False)

    assert result.issues == []
    assert result.passed is True


def test_documento_generico_build_rules_succeeds_with_zero_errors(tmp_path: Path):
    config = _resolved_config(tmp_path)
    service = EvidenceService(JsonEvidenceRepository())

    manifest_path = service.build_rules(config)

    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["skipped_paths"]) == {"manual_dir", "extracted_dir"}


def test_documento_generico_doctor_rules_config_check_passes(tmp_path: Path, monkeypatch):
    # Toolchain checks (pandoc/libreoffice/gh) are host-environment concerns,
    # orthogonal to this front's policy-de-hardcoding scope -- patched the
    # same way tests/integration/test_pipeline_service.py already does, so
    # this test isolates exactly what Front A changed: the "rules_config"
    # check (review_rules) and its supporting manifest/asset checks.
    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_pandoc_executable", lambda paths: "pandoc"
    )
    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_libreoffice_executable", lambda paths: "soffice"
    )
    monkeypatch.setattr("shutil.which", lambda name: "gh")

    config = _resolved_config(tmp_path)
    (Path(config["paths"]["context_dir"])).mkdir(exist_ok=True)
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    evidence_repo = JsonEvidenceRepository()
    evidence_service = EvidenceService(evidence_repo)
    evidence_service.build_rules(config)
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    tool_resolver = SystemToolResolverAdapter()
    doctor_service = DoctorService(evidence_repo, asset_service, tool_resolver)

    result = doctor_service.run_doctor("documento-generico-doc", config, strict=False)

    rules_check = next(c for c in result.checks if c.name == "rules_config")
    assert rules_check.ok is True, rules_check.detail


def test_documento_generico_full_prep_pipeline_passes_with_zero_errors(tmp_path: Path, monkeypatch):
    """Task 11.10 (Front G closeout): the WHOLE `prep` stage set --
    including the new Front G "gap-report" stage -- must still pass
    end-to-end for `documento-generico`, proving Front G did not regress
    the founding Front A acceptance gate this file exists to protect."""
    from docs.application.asset import AssetService
    from docs.application.collection import CollectionService
    from docs.application.context import ContextService
    from docs.application.context_pack import ContextPackService
    from docs.application.docx_assembly import DocxRendererAdapter
    from docs.application.format_audit import FormatAuditService
    from docs.application.ingest import IngestService
    from docs.application.pipeline import PipelineService
    from docs.application.qa import QaService
    from docs.application.review import ReviewService
    from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter
    from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
    from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter
    from docs.infrastructure.ingest.filetype_detector_adapter import FiletypeDetectorAdapter
    from docs.infrastructure.persistence.context_markdown import ContextMarkdownAdapter
    from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository
    from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
    from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
    from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository

    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_pandoc_executable", lambda paths: "pandoc"
    )
    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_libreoffice_executable", lambda paths: "soffice"
    )
    monkeypatch.setattr("shutil.which", lambda name: "gh")

    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    Path(tmp_path / "documents" / "doc1").mkdir(parents=True)
    Path(tmp_path / "context").mkdir()
    sections_dir = tmp_path / "sections"

    config = _resolved_config(tmp_path)
    config["paths"].update(
        {
            "sections_dir": str(sections_dir),
            "source_manifest": str(tmp_path / "source.json"),
            "issues_manifest": str(tmp_path / "issues.json"),
            "code_evidence_manifest": str(tmp_path / "code-evidence.json"),
            "fact_ledger": str(tmp_path / "00-fact-ledger.md"),
            "prompts_dir": str(tmp_path / "prompts"),
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

    summary = pipeline.run_pipeline("doc1", template, config, "prep", repo_root=tmp_path, strict=False)

    failed = [s for s in summary["stages"] if not s["ok"]]
    assert summary["passed"] is True, failed
    assert [s["stage"] for s in summary["stages"]][:9] == [
        "doctor", "build-rules", "review-rules", "collect-sources",
        "collect-code-evidence", "collect-issues", "build-ledger",
        "build-sections", "gap-report",
    ]
    # draft mode: gaps are advisory, never block -- but still reported.
    report = json.loads((sections_dir / "gap-report.json").read_text(encoding="utf-8"))
    assert report["context_gaps"], "documento-generico's required topics are never filled in this test"
    # CRITICAL-1 regression (verify-report-pr6.md): every section here is
    # genuinely freshly-scaffolded by the real build-sections stage above,
    # never hand-written -- section_gaps must report real content gaps too,
    # never silently self-satisfied by the harness's own PENDIENTE text.
    assert report["section_gaps"], "freshly-scaffolded sections must report real content gaps"
    introduccion_gap = next(g for g in report["section_gaps"] if g["section_id"] == "introduccion")
    assert set(introduccion_gap["missing"]) == {"tema", "objetivo", "alcance"}
