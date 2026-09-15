# tests/unit/application/test_pipeline_service.py
"""Unit coverage for PipelineService (document-pipeline spec: `Application-
Layer Test Coverage`). Constructs the service with a fake evidence
repository and inert placeholders for the collaborators a given method does
not touch -- exercises `rules_manifest_state` in isolation, distinct from
the repository-backed integration coverage in
tests/integration/test_pipeline_service.py."""
from __future__ import annotations

from pathlib import Path

from docs.application.pipeline import PipelineService
from docs.application.pipeline_metadata import PipelineMetadataService
from docs.application.stage_operation_planner import StageOperationPlanner


class _FakeEvidenceRepository:
    def file_exists(self, path: Path) -> bool:
        return True

    def file_size(self, path: Path) -> int:
        return 42


def _service(evidence_repository) -> PipelineService:
    unused = object()
    return PipelineService(
        doctor_service=unused,
        evidence_service=unused,
        evidence_repository=evidence_repository,
        collection_service=unused,
        source_repository=unused,
        review_service=unused,
        context_pack_service=unused,
        context_repository=unused,
        docx_assembly_service=unused,
        format_audit_service=unused,
        qa_service=unused,
        workspace=unused,
        ingest_service=unused,
        context_service=unused,
    )


def test_rules_manifest_state_reads_existence_and_size_through_the_repository():
    service = _service(_FakeEvidenceRepository())

    exists, size = service.rules_manifest_state({"paths": {"rules_manifest": "whatever.json"}})

    assert (exists, size) == (True, 42)


def test_rules_manifest_state_skips_size_lookup_when_manifest_absent():
    class _AbsentRepo(_FakeEvidenceRepository):
        def file_exists(self, path: Path) -> bool:
            return False

        def file_size(self, path: Path) -> int:
            raise AssertionError("file_size must not be called when the manifest is absent")

    service = _service(_AbsentRepo())

    exists, size = service.rules_manifest_state({"paths": {"rules_manifest": "missing.json"}})

    assert (exists, size) == (False, 0)


def test_pipeline_metadata_calculates_next_monotonic_build_version(tmp_path):
    workspace = type("Workspace", (), {"doc_root": lambda self, doc_id: tmp_path / doc_id})()
    runs_dir = tmp_path / "alpha" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "old.json").write_text('{"build_version": 2}', encoding="utf-8")
    (runs_dir / "new.json").write_text('{"build_version": 7}', encoding="utf-8")
    (runs_dir / "invalid.json").write_text("not json", encoding="utf-8")

    service = PipelineMetadataService(workspace)

    assert service.next_build_version("alpha", {}) == 8


def test_pipeline_metadata_resolves_configured_draft_docx_name(tmp_path):
    workspace = type("Workspace", (), {"doc_root": lambda self, doc_id: tmp_path / doc_id})()

    assert PipelineMetadataService(workspace).resolve_draft_docx_name(
        "alpha", {"output": {"draft_name": "custom.docx"}}
    ) == "custom.docx"


def test_pipeline_service_delegates_metadata_compatibility_methods():
    service = _service(_FakeEvidenceRepository())

    class MetadataService:
        def next_build_version(self, doc_id, config):
            assert (doc_id, config) == ("doc", {"paths": {}})
            return 12

        def resolve_draft_docx_name(self, doc_id, config):
            assert (doc_id, config) == ("doc", {"paths": {}})
            return "delegated.docx"

    service.metadata_service = MetadataService()

    assert service._next_build_version("doc", {"paths": {}}) == 12
    assert service._resolve_draft_docx_name("doc", {"paths": {}}) == "delegated.docx"


def test_build_section_delegates_to_section_service():
    service = _service(_FakeEvidenceRepository())
    expected = Path("section.md")

    class SectionService:
        def build_section(self, doc_id, template, section_id, config):
            assert (doc_id, template, section_id, config) == ("doc", "template", "intro", {"paths": {}})
            return expected

    service.section_service = SectionService()

    assert service.build_section("doc", "template", "intro", {"paths": {}}) == expected


def test_stage_callables_delegates_to_stage_operation_planner():
    service = _service(_FakeEvidenceRepository())
    expected = {"doctor": lambda: (True, "ok")}

    class StagePlanner:
        def plan(self, pipeline, doc_id, template, config, repo_root, strict, renderer):
            assert pipeline is service
            assert (doc_id, template, config, repo_root, strict, renderer) == (
                "doc", "template", {"paths": {}}, Path("repo"), True, "renderer"
            )
            return expected

    service.stage_planner = StagePlanner()

    assert service._stage_callables("doc", "template", {"paths": {}}, Path("repo"), True, "renderer") is expected


def test_run_pipeline_uses_reusable_flat_pipeline_boundary(monkeypatch):
    service = _service(_FakeEvidenceRepository())
    expected = {"stage_set": "prep", "passed": True, "stages": []}
    captured = {}

    class Flat:
        def __init__(self, *, operations):
            captured["operations"] = operations

        def run(self, stage_set, *, strict, stages):
            captured["args"] = (stage_set, strict, stages)
            return expected

    class Renderer:
        def stage_plan(self):
            return []

    monkeypatch.setattr("docs.application.pipeline.FlatPipelineV2Adapter", Flat)
    monkeypatch.setattr(
        "docs.application.pipeline.pipeline_stage_plan",
        lambda stage_set, renderer_stages: (("doctor", True),),
    )
    monkeypatch.setattr(service, "log_run", lambda *args: Path("run.json"))

    result = service.run_pipeline(
        "doc", "template", {"paths": {}}, "prep", Path("repo"), strict=True, renderer=Renderer()
    )

    assert result is expected
    assert captured["args"] == ("prep", True, (("doctor", True),))


def test_run_pipeline_honors_application_pipeline_stage_plan_patch(tmp_path, monkeypatch):
    class SourceRepository:
        def run_git_rev_parse_head(self, repo_root):
            return "abc123"

    class Renderer:
        def stage_plan(self):
            return []

    service = _service(_FakeEvidenceRepository())
    service.source_repository = SourceRepository()
    monkeypatch.setattr("docs.application.pipeline.pipeline_stage_plan", lambda stage_set, renderer_stages: [])

    summary = service.run_pipeline(
        "alpha",
        object(),
        {"paths": {"runs_dir": str(tmp_path / "runs")}},
        "prep",
        tmp_path,
        renderer=Renderer(),
    )

    assert summary["stages"] == []


def test_stage_operation_planner_preserves_stage_callable_order():
    service = _service(_FakeEvidenceRepository())
    template = type("Template", (), {"sections": []})()
    renderer = type("Renderer", (), {})()

    callables = StageOperationPlanner().plan(service, "doc", template, {}, Path("repo"), False, renderer)

    assert list(callables) == [
        "doctor",
        "build-rules",
        "review-rules",
        "collect-sources",
        "collect-code-evidence",
        "collect-issues",
        "build-ledger",
        "build-sections",
        "gap-report",
        "pack-context",
        "review-document",
        "build-docx",
        "build-html",
        "build-pdf",
        "format-audit-docx",
        "ingest",
        "generate-visuals",
        "build-context-files",
        "build-context-index",
        "qa-docx",
    ]


def test_run_pipeline_records_generated_cover_provenance(tmp_path, monkeypatch):
    class SourceRepository:
        def run_git_rev_parse_head(self, repo_root):
            return "abc123"

    service = _service(_FakeEvidenceRepository())
    service.source_repository = SourceRepository()
    monkeypatch.setattr("docs.application.pipeline.pipeline_stage_plan", lambda stage_set, renderer_stages: [])

    summary = service.run_pipeline(
        "alpha",
        object(),
        {
            "title": "Report",
            "cover": {"mode": "generated", "variant": "minimal", "slots": {"title": "{{title}}"}},
            "paths": {"runs_dir": str(tmp_path / "runs")},
        },
        "assemble",
        tmp_path,
        renderer=type("Renderer", (), {"stage_plan": lambda self: []})(),
    )

    assert summary["cover"] == {"mode": "generated", "variant": "minimal", "missing_slots": []}


def test_list_runs_delegates_to_run_history_service():
    service = _service(_FakeEvidenceRepository())
    expected = [{"command": "verify"}]

    class _RunHistory:
        def list_runs(self, doc_id, config, limit=20):
            assert (doc_id, config, limit) == ("doc1", {"paths": {}}, 3)
            return expected

    service.run_history = _RunHistory()

    assert service.list_runs("doc1", {"paths": {}}, limit=3) is expected
