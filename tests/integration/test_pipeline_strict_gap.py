# tests/integration/test_pipeline_strict_gap.py
"""Integration coverage for the gap-report draft/strict wiring (design.md
Decision 7, spec: document-pipeline "Machine-Readable Gap Report" /
"Draft mode proceeds with PENDIENTE markers" / "Strict mode blocks on
gaps"). Exercises the REAL `PipelineService.run_pipeline("prep", ...)`
sequence -- not a fake stage callable -- so the wiring can never ship inert
(PR5 CRITICAL lesson: call the real consumer, assert the artifact arrives)."""
from __future__ import annotations

import json
from pathlib import Path

from docs.application.asset import AssetService
from docs.application.collection import CollectionService
from docs.application.context import ContextService
from docs.application.context_pack import ContextPackService
from docs.application.docx_assembly import DocxRendererAdapter
from docs.application.doctor import DoctorService
from docs.application.evidence import EvidenceService
from docs.application.format_audit import FormatAuditService
from docs.application.ingest import IngestService
from docs.application.pipeline import PipelineService
from docs.application.qa import QaService
from docs.application.review import ReviewService
from docs.domain.models.template import Field, Template, Topic
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.ingest.filetype_detector_adapter import FiletypeDetectorAdapter
from docs.infrastructure.persistence.context_markdown import ContextMarkdownAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository

_VALID_RULES_EXTRA = {
    "preliminaries": {
        "roman_pagination": {"enabled": True},
        "body_pagination_start": {"section_id": "introduccion"},
    },
    "format": {
        "page_margins_cm": {
            "cover_policy": "preserve_template",
            "non_cover": {"top": 2.5, "right": 2.5, "bottom": 2.5, "left": 2.5},
        }
    },
    "advisor_overrides": [{"id": "margins-2-5cm-non-cover", "status": "active"}],
}

_TOPIC = Topic(
    id="alumno", title="Alumno", required=True,
    fields=[Field(key="nombre", label="Nombre", required=True)],
)


def _template() -> Template:
    return Template.model_validate(
        {
            "type": "tesina",
            "title": "Tesina",
            "sections": [{"id": "introduccion", "title": "Introducción", "order": 1}],
            "section_contracts": {"introduccion": {"required_content": ["algo"]}},
            "paths": {"extracted_dir_policy": "rules_traceability_only"},
            "context_schema": {"topics": [_TOPIC.model_dump()]},
            **_VALID_RULES_EXTRA,
        }
    )


def _pipeline_config(tmp_path: Path) -> dict:
    return {
        "type": "tesina",
        "title": "Tesina",
        "paths": {
            "rules_manifest": str(tmp_path / "manual-rules.json"),
            "context_dir": str(tmp_path / "context"),
            "sections_dir": str(tmp_path / "sections"),
            "source_manifest": str(tmp_path / "source.json"),
            "issues_manifest": str(tmp_path / "issues.json"),
            "code_evidence_manifest": str(tmp_path / "code-evidence.json"),
            "fact_ledger": str(tmp_path / "00-fact-ledger.md"),
            "prompts_dir": str(tmp_path / "prompts"),
            "extracted_dir_policy": "rules_traceability_only",
        },
        "sections": [{"id": "introduccion", "title": "Introducción", "order": 1}],
        "section_contracts": {"introduccion": {"required_content": ["algo"]}},
        "context_schema": {"topics": [_TOPIC.model_dump()]},
        **_VALID_RULES_EXTRA,
        "evidence_sources": {},
        "privacy": {},
        "project": {},
    }


def _service(tmp_path: Path) -> tuple[PipelineService, Workspace]:
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
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
    service = PipelineService(
        doctor_service, evidence_service, evidence_repo, collection_service, source_repo,
        review_service, context_pack_service, context_repo, docx_assembly_service,
        format_audit_service, qa_service, workspace, ingest_service,
        context_service=context_service,
    )
    return service, workspace


def _patch_doctor_tools(monkeypatch) -> None:
    monkeypatch.setattr("docs.infrastructure.docx.tool_resolver_adapter.resolve_pandoc_executable", lambda paths: "pandoc")
    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_libreoffice_executable", lambda paths: "soffice"
    )


def test_gap_report_stage_is_wired_into_the_prep_stage_plan_after_build_sections():
    from docs.domain.pipeline import pipeline_stage_plan

    stages = [name for name, _fail_fast in pipeline_stage_plan("prep")]
    assert stages.index("gap-report") == stages.index("build-sections") + 1


def test_draft_mode_proceeds_and_gap_report_lists_the_missing_context_field(tmp_path, monkeypatch):
    Path(tmp_path / "context").mkdir()
    Path(tmp_path / "documents" / "doc1").mkdir(parents=True)
    service, _ = _service(tmp_path)
    _patch_doctor_tools(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: None)

    summary = service.run_pipeline(
        "doc1", _template(), _pipeline_config(tmp_path), "prep", repo_root=tmp_path, strict=False
    )

    gap_stage = next(s for s in summary["stages"] if s["stage"] == "gap-report")
    assert gap_stage["ok"] is True
    assert "pack-context" in [s["stage"] for s in summary["stages"]]
    report = json.loads((tmp_path / "sections" / "gap-report.json").read_text(encoding="utf-8"))
    assert report["context_gaps"] == [{"topic_id": "alumno", "missing": ["Nombre"]}]
    # CRITICAL-1 regression (verify-report-pr6.md): "introduccion" is a real,
    # freshly-scaffolded, unedited section here -- its own required_content
    # ("algo") must ALSO show up as a genuine section gap, never silently
    # self-satisfied by the harness's own PENDIENTE placeholder text.
    assert report["section_gaps"] == [{"section_id": "introduccion", "missing": ["algo"]}]


def test_strict_mode_blocks_before_pack_context_when_a_context_field_is_missing(tmp_path, monkeypatch):
    Path(tmp_path / "context").mkdir()
    Path(tmp_path / "documents" / "doc1").mkdir(parents=True)
    service, _ = _service(tmp_path)
    _patch_doctor_tools(monkeypatch)
    # strict mode makes doctor's "gh" check required too (unrelated to the
    # gap-report change) -- fake it present so doctor itself doesn't
    # fail-fast before the pipeline ever reaches gap-report.
    monkeypatch.setattr("shutil.which", lambda name: "gh")

    summary = service.run_pipeline(
        "doc1", _template(), _pipeline_config(tmp_path), "prep", repo_root=tmp_path, strict=True
    )

    assert summary["passed"] is False
    gap_stage = next(s for s in summary["stages"] if s["stage"] == "gap-report")
    assert gap_stage["ok"] is False
    stage_names = [s["stage"] for s in summary["stages"]]
    assert "pack-context" not in stage_names, "strict mode must stop before producing final output"
    report = json.loads((tmp_path / "sections" / "gap-report.json").read_text(encoding="utf-8"))
    assert report["context_gaps"]


def test_strict_mode_still_blocks_on_the_untouched_scaffold_after_filling_only_context(tmp_path, monkeypatch):
    # CRITICAL-1 regression (verify-report-pr6.md): filling ONLY the context
    # field is NOT enough -- "introduccion"'s section_contract still
    # requires content ("algo") that build-sections has only ever
    # SCAFFOLDED, never actually written. Before the fix this test asserted
    # the OPPOSITE (strict proceeds) -- that assertion only held because
    # requirement_present() trivially self-matched the harness's own
    # "PENDIENTE: documentar algo con evidencia..." scaffold line. Updated
    # here, explicitly, per the coordinator's fix-verify instruction: an
    # existing test that asserts the old buggy behavior encodes the bug.
    Path(tmp_path / "context").mkdir()
    Path(tmp_path / "documents" / "doc1").mkdir(parents=True)
    service, _ = _service(tmp_path)
    service.context_repository.write_topic("doc1", _TOPIC, {"nombre": "Ada"})
    _patch_doctor_tools(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: "gh")

    summary = service.run_pipeline(
        "doc1", _template(), _pipeline_config(tmp_path), "prep", repo_root=tmp_path, strict=True
    )

    gap_stage = next(s for s in summary["stages"] if s["stage"] == "gap-report")
    assert gap_stage["ok"] is False
    assert "pack-context" not in [s["stage"] for s in summary["stages"]]
    report = json.loads((tmp_path / "sections" / "gap-report.json").read_text(encoding="utf-8"))
    assert report["context_gaps"] == []
    assert report["section_gaps"] == [{"section_id": "introduccion", "missing": ["algo"]}]


def test_strict_mode_proceeds_once_the_section_is_genuinely_written(tmp_path, monkeypatch):
    # The REAL counterpart: the section is genuinely authored (not the
    # harness's own PENDIENTE scaffold) BEFORE the pipeline runs. Written
    # WITHOUT harness frontmatter, so build-sections' own idempotency check
    # (not "managed_by docs-harness") defers to a proposal file instead of
    # clobbering it -- the real, edited content is what gap-report reads.
    Path(tmp_path / "context").mkdir()
    Path(tmp_path / "documents" / "doc1").mkdir(parents=True)
    service, _ = _service(tmp_path)
    service.context_repository.write_topic("doc1", _TOPIC, {"nombre": "Ada"})
    service.review_service.repository.write_section(
        "doc1", 1, "introduccion", "# Introducción\n\nEsto documenta algo con evidencia real y verificable.\n"
    )
    _patch_doctor_tools(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: "gh")

    summary = service.run_pipeline(
        "doc1", _template(), _pipeline_config(tmp_path), "prep", repo_root=tmp_path, strict=True
    )

    gap_stage = next(s for s in summary["stages"] if s["stage"] == "gap-report")
    assert gap_stage["ok"] is True, json.loads(
        (tmp_path / "sections" / "gap-report.json").read_text(encoding="utf-8")
    )
    assert "pack-context" in [s["stage"] for s in summary["stages"]]
