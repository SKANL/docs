# tests/integration/test_pipeline_service.py
from __future__ import annotations

import json
from pathlib import Path

from docs.application.collection import CollectionService
from docs.application.context_pack import ContextPackService
from docs.application.doctor import DoctorService
from docs.application.docx_assembly import DocxAssemblyService
from docs.application.evidence import EvidenceService
from docs.application.format_audit import FormatAuditService
from docs.application.pipeline import PipelineService
from docs.application.qa import QaService
from docs.application.review import ReviewService
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository
from docs.application.asset import AssetService


def _service(tmp_path) -> tuple[PipelineService, Workspace]:
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    evidence_repo = JsonEvidenceRepository()
    section_repo = JsonSectionRepository(workspace)
    source_repo = FilesystemSourceRepository()
    context_repo = JsonContextRepository(workspace)
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    evidence_service = EvidenceService(evidence_repo)
    review_service = ReviewService(section_repo)
    collection_service = CollectionService(source_repo, evidence_repo)
    context_pack_service = ContextPackService(section_repo, evidence_repo, evidence_service, review_service)
    docx_assembly_service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service)
    format_audit_service = FormatAuditService(PythonDocxAuditAdapter())
    qa_service = QaService(LibreOfficeQaAdapter(), format_audit_service)
    doctor_service = DoctorService(evidence_repo, asset_service)
    service = PipelineService(
        doctor_service, evidence_service, evidence_repo, collection_service, source_repo,
        review_service, context_pack_service, context_repo, docx_assembly_service,
        format_audit_service, qa_service, workspace,
    )
    return service, workspace


def test_log_run_writes_a_json_record_under_the_document_runs_dir(tmp_path):
    service, workspace = _service(tmp_path)
    config = {"paths": {}}
    path = service.log_run("doc1", config, tmp_path, "pipeline-prep", {"passed": True, "stages": []})
    assert path.parent == workspace.doc_root("doc1") / "runs"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["command"] == "pipeline-prep"
    assert record["passed"] is True
    assert "timestamp" in record
    assert "git_commit" in record


def test_log_run_honors_configured_runs_dir_override(tmp_path):
    service, _ = _service(tmp_path)
    override_dir = tmp_path / "custom-runs"
    config = {"paths": {"runs_dir": str(override_dir)}}
    path = service.log_run("doc1", config, tmp_path, "pipeline-prep", {"passed": True})
    assert path.parent == override_dir


def test_list_runs_returns_empty_list_when_runs_dir_missing(tmp_path):
    service, _ = _service(tmp_path)
    assert service.list_runs("doc1", {"paths": {}}) == []


def test_list_runs_returns_records_most_recent_first(tmp_path):
    service, _ = _service(tmp_path)
    config = {"paths": {}}
    service.log_run("doc1", config, tmp_path, "pipeline-prep", {"n": 1})
    service.log_run("doc1", config, tmp_path, "pipeline-assemble", {"n": 2})
    records = service.list_runs("doc1", config)
    assert [r["n"] for r in records] == [2, 1]


def test_list_runs_respects_limit(tmp_path):
    service, _ = _service(tmp_path)
    config = {"paths": {}}
    for i in range(3):
        service.log_run("doc1", config, tmp_path, "pipeline-prep", {"n": i})
    assert len(service.list_runs("doc1", config, limit=2)) == 2


def test_list_runs_skips_malformed_json_files(tmp_path):
    service, workspace = _service(tmp_path)
    config = {"paths": {}}
    service.log_run("doc1", config, tmp_path, "pipeline-prep", {"n": 1})
    (workspace.doc_root("doc1") / "runs" / "broken.json").write_text("not json", encoding="utf-8")
    records = service.list_runs("doc1", config)
    assert len(records) == 1
