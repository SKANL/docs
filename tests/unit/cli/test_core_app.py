# tests/unit/cli/test_core_app.py
"""`docs guide` (design.md item B: agent contract, Task 10.4). No workspace
fixture needed -- the guide is static content, not document-scoped."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import docs.cli._shared as shared
from docs.application.flat_pipeline_compatibility import FlatPipelineCompatibilityAdapter, route_for
from docs.cli._shared import Deps
from docs.cli.commands.core_app import _run_compatible_pipeline
from docs.cli.main import app

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_guide_prints_the_full_agents_md_content():
    result = runner.invoke(app, ["guide"])
    assert result.exit_code == 0
    repo_root_text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert result.output.strip() == repo_root_text.strip()


def test_guide_documents_the_end_to_end_workflow_commands():
    result = runner.invoke(app, ["guide"])
    for command in ("pipeline ingest", "review-section", "pipeline assemble", "docs.config.json"):
        assert command in result.output


# --- pipeline --format (SDD harness-generality-and-revision, PR2, item C-html) --

_TEMPLATE = {
    "type": "tesina",
    "title": "Tesina",
    "sections": [{"id": "introduccion", "title": "Introducción", "order": 1, "required": False}],
    "section_contracts": {"introduccion": {}},
}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    documents = tmp_path / "documents"
    templates = tmp_path / "templates"
    documents.mkdir()
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(documents))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    return tmp_path


def _new_doc(doc_id="doc1"):
    Deps().documents.create(doc_id, "tesina")


def _fake_v2_assemble(seen_formats):
    def run_v2_assemble(deps, resolved, strict, formats):
        del deps, resolved
        seen_formats.append(formats)
        requested = formats or ["docx"]
        return [
            {"stage_set": "assemble", "strict": strict, "passed": True, "stages": []}
            for _ in requested
        ]

    return run_v2_assemble


def test_deps_registers_the_html_renderer(workspace):
    assert "html" in Deps().renderers
    assert Deps().renderers["html"].output_format == "html"


def test_deps_registers_the_pdf_renderer(workspace):
    assert "pdf" in Deps().renderers
    assert Deps().renderers["pdf"].output_format == "pdf"


def test_deps_exposes_only_the_lazy_native_pipeline(workspace):
    deps = Deps()

    assert not hasattr(deps, "legacy_pipeline")
    assert isinstance(deps.pipeline, shared._LazyPipelineService)


def test_pipeline_format_pdf_selects_the_pdf_renderer(workspace, monkeypatch):
    _new_doc()
    seen_formats: list[str] = []
    monkeypatch.setattr("docs.cli.commands.core_app._run_v2_assemble", _fake_v2_assemble(seen_formats))

    result = runner.invoke(app, ["pipeline", "assemble", "--format", "pdf"])

    assert result.exit_code == 0
    assert seen_formats == [["pdf"]]


def test_pipeline_format_html_selects_the_html_renderer(workspace, monkeypatch):
    _new_doc()
    seen_formats: list[str] = []
    monkeypatch.setattr("docs.cli.commands.core_app._run_v2_assemble", _fake_v2_assemble(seen_formats))

    result = runner.invoke(app, ["pipeline", "assemble", "--format", "html"])

    assert result.exit_code == 0
    assert seen_formats == [["html"]]


def test_pipeline_format_is_repeatable_and_builds_each_requested_format(workspace, monkeypatch):
    _new_doc()
    seen_formats: list[str] = []
    monkeypatch.setattr("docs.cli.commands.core_app._run_v2_assemble", _fake_v2_assemble(seen_formats))

    result = runner.invoke(app, ["pipeline", "assemble", "--format", "html", "--format", "docx"])

    assert result.exit_code == 0
    assert seen_formats == [["html", "docx"]]


def test_pipeline_no_format_flag_keeps_the_config_driven_docx_default(workspace, monkeypatch):
    # No flag -- today's behavior: the renderer comes from `output.format` in
    # the merged template/document config (default "docx"), same as before
    # `--format` existed. Never hardcode "docx" as the CLI default; that would
    # silently ignore an explicit `output.format` in a template's config.
    _new_doc()
    seen_formats: list[str] = []
    monkeypatch.setattr("docs.cli.commands.core_app._run_v2_assemble", _fake_v2_assemble(seen_formats))

    result = runner.invoke(app, ["pipeline", "assemble"])

    assert result.exit_code == 0
    assert seen_formats == [None]


def test_pipeline_json_output_stays_a_single_object_for_one_format(workspace, monkeypatch):
    # Backward compatibility: existing callers parse a single JSON object
    # (`json.loads(result.output)`), not a list -- must not change shape when
    # only one format is built (the default, unflagged path).
    _new_doc()
    monkeypatch.setattr(
        "docs.cli.commands.core_app._run_v2_assemble",
        _fake_v2_assemble([]),
    )

    result = runner.invoke(app, ["pipeline", "assemble", "--json"])

    payload = json.loads(result.output)
    assert isinstance(payload, dict)
    assert payload["passed"] is True


def test_pipeline_json_output_is_a_list_when_multiple_formats_requested(workspace, monkeypatch):
    _new_doc()
    monkeypatch.setattr(
        "docs.cli.commands.core_app._run_v2_assemble",
        _fake_v2_assemble([]),
    )

    result = runner.invoke(app, ["pipeline", "assemble", "--format", "html", "--format", "docx", "--json"])

    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 2


def test_flat_pipeline_policy_routes_v2_slices_and_leaves_prep_legacy():
    assert route_for("ingest") is not None
    assert route_for("prepare") is not None
    assert route_for("prep") is None
    assert route_for("assemble").backend == "v2-runtime"
    assert route_for("all").backend == "v2-runtime"
    assert route_for("unsupported") is None


def test_flat_pipeline_all_adapter_preserves_historical_order_without_ingest():
    calls: list[str] = []

    def run_stage(stage_set: str) -> dict[str, object]:
        calls.append(stage_set)
        return {
            "stage_set": stage_set,
            "strict": False,
            "passed": True,
            "stages": [{"stage": stage_set, "ok": True, "duration_s": 0.0, "detail": stage_set}],
        }

    adapter = FlatPipelineCompatibilityAdapter(
        prep=lambda: run_stage("prep"),
        review_document=lambda: run_stage("review-document"),
        assemble=lambda: [run_stage("assemble")],
    )

    summary = adapter.run_all()

    assert calls == ["prep", "review-document", "assemble"]
    assert [stage["stage"] for stage in summary["stages"]] == [
        "prep",
        "review-document",
        "assemble",
    ]
    assert summary["passed"] is True


def test_flat_pipeline_assemble_projects_v2_runtime_and_preserves_legacy_summary(
    workspace, monkeypatch
):
    _new_doc()
    calls: list[tuple[str, bool, str]] = []

    class _Report:
        def to_dict(self):
            return {
                "succeeded": True,
                "execution": {
                    "results": [
                        {
                            "stage": "build-docx",
                            "ok": True,
                            "outcome": "succeeded",
                            "artifacts": [],
                            "warnings": [],
                            "errors": [],
                        }
                    ]
                },
            }

    class _V2Service:
        def run(self, run_id, *, publish, pipeline_id):
            calls.append((run_id, publish, pipeline_id))
            return _Report()

    monkeypatch.setattr(
        "docs.cli.commands.core_app.create_v2_service",
        lambda deps, output_format, policy, document, pipeline_id, publication_destination: _V2Service(),
    )
    monkeypatch.setattr(
        "docs.application.pipeline.PipelineService.run_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy backend used")),
    )

    result = runner.invoke(app, ["pipeline", "assemble", "--format", "docx", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["stage_set"] == "assemble"
    assert payload["passed"] is True
    assert payload["stages"][0]["stage"] == "build-docx"
    assert payload["stages"][0]["ok"] is True
    assert calls == [("cli-assemble-docx", True, "document")]


def test_flat_pipeline_all_fails_when_v2_execution_stage_fails(
    workspace, monkeypatch
):
    _new_doc()

    class _Report:
        def to_dict(self):
            return {
                "succeeded": True,
                "execution": {
                    "results": [
                        {
                            "stage": "build-docx",
                            "ok": False,
                            "outcome": "failed",
                            "errors": [{"message": "render failed"}],
                        }
                    ]
                },
            }

    class _V2Service:
        def run(self, run_id, *, publish, pipeline_id):
            del run_id, publish, pipeline_id
            return _Report()

    def legacy_run(self, doc_id, template, config, selected, repo_root, strict=False, renderer=None):
        del self, doc_id, template, config, repo_root, strict, renderer
        return {
            "stage_set": selected,
            "strict": False,
            "passed": True,
            "stages": [{"stage": selected, "ok": True, "duration_s": 0.0, "detail": selected}],
        }

    monkeypatch.setattr("docs.cli.commands.core_app.create_v2_service", lambda *args, **kwargs: _V2Service())
    monkeypatch.setattr("docs.application.pipeline.PipelineService.run_pipeline", legacy_run)
    monkeypatch.setattr(
        "docs.application.pipeline.PipelineService._stage_callables",
        lambda *args, **kwargs: {
            name: (lambda name=name: (True, name))
            for name in (
                "doctor", "build-rules", "review-rules", "collect-sources",
                "collect-code-evidence", "collect-issues", "build-ledger",
                "build-sections", "gap-report", "pack-context", "review-document",
            )
        },
    )

    result = runner.invoke(app, ["pipeline", "all", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    assert payload["stages"][-1]["stage"] == "build-docx"
    assert payload["stages"][-1]["ok"] is False


@pytest.mark.parametrize("execution", [{}, {"results": "invalid"}, {"results": [None, "invalid"]}])
def test_flat_pipeline_assemble_rejects_missing_or_invalid_execution_results(
    workspace, monkeypatch, execution
):
    _new_doc()

    class _Report:
        def to_dict(self):
            return {"succeeded": True, "execution": execution}

    class _V2Service:
        def run(self, run_id, *, publish, pipeline_id):
            del run_id, publish, pipeline_id
            return _Report()

    monkeypatch.setattr(
        "docs.cli.commands.core_app.create_v2_service",
        lambda *args, **kwargs: _V2Service(),
    )

    result = runner.invoke(app, ["pipeline", "assemble", "--format", "docx", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    assert payload["stages"] == [
        {
            "stage": "assemble",
            "ok": False,
            "duration_s": 0.0,
            "detail": json.dumps(
                {"succeeded": True, "execution": execution},
                ensure_ascii=False,
                sort_keys=True,
            ),
            "error": {
                "code": "pipeline.malformed_v2_execution",
                "message": "The v2 assemble report must contain execution.results with at least one mapping stage.",
            },
        }
    ]


def test_flat_pipeline_assemble_publishes_to_draft_and_preserves_final(
    workspace, monkeypatch
):
    _new_doc()
    doc_root = Deps().workspace.doc_root("doc1")
    draft = doc_root / "output" / "draft" / "doc1-draft.docx"
    final = doc_root / "output" / "final" / "doc1-draft.docx"
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_text("existing-final", encoding="utf-8")
    seen: list[Path] = []

    class _Report:
        def to_dict(self):
            return {
                "succeeded": True,
                "execution": {"results": [{"stage": "build-docx", "ok": True}]},
            }

    class _V2Service:
        def run(self, run_id, *, publish, pipeline_id):
            assert publish is True
            assert pipeline_id == "document"
            destination = seen[-1]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("new-draft", encoding="utf-8")
            return _Report()

    def _create_service(deps, output_format, policy, document, pipeline_id, publication_destination):
        del deps, output_format, policy, document, pipeline_id
        seen.append(publication_destination)
        return _V2Service()

    monkeypatch.setattr("docs.cli.commands.core_app.create_v2_service", _create_service)

    result = runner.invoke(app, ["pipeline", "assemble", "--format", "docx", "--json"])

    assert result.exit_code == 0
    assert seen == [draft]
    assert draft.read_text(encoding="utf-8") == "new-draft"
    assert final.read_text(encoding="utf-8") == "existing-final"


def test_flat_pipeline_ingest_preserves_legacy_summary_shape_and_uses_v2(workspace, monkeypatch):
    _new_doc()
    calls: list[tuple[str, str]] = []

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            calls.append((document_id, str(document_root)))
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())
    monkeypatch.setattr(
        "docs.application.pipeline.PipelineService.run_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy backend used")),
    )

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["stage_set"] == "ingest"
    assert payload["strict"] is False
    assert payload["passed"] is True
    assert payload["stages"][0]["stage"] == "ingest-sources"
    assert payload["stages"][0]["ok"] is True
    assert {"stage", "ok", "duration_s", "detail"} == set(payload["stages"][0])
    assert calls == [("doc1", str(Deps().workspace.doc_root("doc1")))]


def test_flat_pipeline_prepare_projects_all_v2_stages_and_preserves_report_detail(workspace, monkeypatch):
    _new_doc()
    source_report = {
        "schema": "docs.sources/v2",
        "document_id": "doc1",
        "succeeded": True,
        "stages": [
            {"name": "ingest-sources", "succeeded": True, "result": {"processed": 1}},
            {"name": "normalize-sources", "succeeded": True, "result": {"count": 1}},
            {"name": "compile-structure", "succeeded": True, "result": {"parts": 2}},
        ],
        "artifacts": ["sections/v2-structure.json"],
        "warnings": [{"code": "source.advisory", "message": "kept"}],
        "errors": [{"code": "source.detail", "message": "non-blocking detail"}],
    }

    class _SourcePipeline:
        def prepare(self, document_id, document_root, config):
            del document_id, document_root, config
            return source_report

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "prepare", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["stage_set"] == "prepare"
    assert payload["passed"] is True
    assert [stage["stage"] for stage in payload["stages"]] == [
        "ingest-sources", "normalize-sources", "compile-structure"
    ]
    assert all(stage["ok"] is True for stage in payload["stages"])
    details = [json.loads(stage["detail"]) for stage in payload["stages"]]
    assert all(detail["stages"] == source_report["stages"] for detail in details)
    assert all(detail["artifacts"] == source_report["artifacts"] for detail in details)
    assert all(detail["warnings"] == source_report["warnings"] for detail in details)
    assert all(detail["errors"] == source_report["errors"] for detail in details)
    assert payload["warnings"] == source_report["warnings"]
    assert payload["errors"] == source_report["errors"]


def test_flat_pipeline_prepare_strict_is_explicitly_advisory(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def prepare(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [
                    {"name": name, "succeeded": True, "result": {}}
                    for name in ("ingest-sources", "normalize-sources", "compile-structure")
                ],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "prepare", "--strict", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["strict"] is True
    assert payload["strict_policy"]["mode"] == "advisory"
    assert payload["warnings"][0]["code"] == "pipeline.strict_advisory"
    assert "prepare" in payload["warnings"][0]["message"]
    assert "ingest" not in payload["warnings"][0]["message"]


def test_flat_pipeline_prepare_preserves_downstream_skips_and_returns_failure(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def prepare(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": False,
                "stages": [
                    {"name": "ingest-sources", "succeeded": False, "result": {"status": "failed"}},
                    {"name": "normalize-sources", "succeeded": False, "skipped": True,
                     "result": {"status": "skipped", "depends_on": "ingest-sources"}},
                    {"name": "compile-structure", "succeeded": False, "skipped": True,
                     "result": {"status": "skipped", "depends_on": "normalize-sources"}},
                ],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "prepare", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    assert [stage["ok"] for stage in payload["stages"]] == [False, False, False]
    detail = json.loads(payload["stages"][2]["detail"])
    assert detail["stages"][2]["skipped"] is True


def test_flat_pipeline_prepare_projects_skips_as_skip_records_in_json_and_human_output(
    workspace, monkeypatch
):
    _new_doc()

    class _SourcePipeline:
        def prepare(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": False,
                "stages": [
                    {"name": "ingest-sources", "succeeded": True, "result": {}},
                    {
                        "name": "normalize-sources",
                        "succeeded": False,
                        "skipped": True,
                        "result": {"status": "skipped", "depends_on": "ingest-sources"},
                    },
                    {
                        "name": "compile-structure",
                        "succeeded": False,
                        "skipped": True,
                        "result": {"status": "skipped", "depends_on": "normalize-sources"},
                    },
                ],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    json_result = runner.invoke(app, ["pipeline", "prepare", "--json"])
    assert json_result.exit_code == 1
    payload = json.loads(json_result.output)
    assert payload["passed"] is False
    assert payload["stages"][0]["ok"] is True
    assert payload["stages"][1]["ok"] is False
    assert payload["stages"][1]["skipped"] is True
    assert payload["stages"][2]["ok"] is False
    assert payload["stages"][2]["skipped"] is True

    human_result = runner.invoke(app, ["pipeline", "prepare"])
    assert human_result.exit_code == 1
    assert "- SKIP `normalize-sources`" in human_result.output
    assert "- SKIP `compile-structure`" in human_result.output
    assert "- FAIL `normalize-sources`" not in human_result.output


def test_flat_pipeline_prepare_strict_policy_errors_use_prepare_route_wording(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def prepare(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [
                    {"name": name, "succeeded": True, "result": {}}
                    for name in ("ingest-sources", "normalize-sources", "compile-structure")
                ],
                "artifacts": [],
                "strict_policy": "malformed",
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "prepare", "--strict", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    detail = json.loads(payload["stages"][0]["detail"])
    assert "v2 prepare strict_policy" in detail["errors"][0]["message"]
    assert "v2 ingest strict_policy" not in detail["errors"][0]["message"]


def test_flat_pipeline_rejects_contradictory_skipped_success_stage(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [
                    {
                        "name": "ingest-sources",
                        "succeeded": True,
                        "skipped": True,
                        "result": {"status": "skipped"},
                    }
                ],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"
    assert detail["error"] == {"error": "v2 source pipeline returned contradictory skipped success values"}


def test_flat_pipeline_rejects_non_boolean_skipped_stage_value(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [
                    {
                        "name": "ingest-sources",
                        "succeeded": True,
                        "skipped": "yes",
                        "result": {},
                    }
                ],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"
    assert "v2 ingest" in detail["errors"][0]["message"]
    assert "skipped" in detail["errors"][0]["message"]


def test_flat_pipeline_prepare_rejects_report_with_no_stages(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def prepare(self, document_id, document_root, config):
            del document_id, document_root, config
            return {"schema": "docs.sources/v2", "document_id": "doc1", "succeeded": True, "stages": [], "artifacts": []}

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "prepare", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    assert payload["stages"][0]["stage"] == "prepare"
    assert json.loads(payload["stages"][0]["detail"])["errors"][0]["code"] == "pipeline.empty_v2_report"


def test_flat_pipeline_rejects_v2_report_with_missing_document_id(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"
    assert "document_id" in detail["errors"][0]["message"]


def test_flat_pipeline_rejects_v2_report_with_wrong_document_id(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "other-doc",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    detail = json.loads(json.loads(result.output)["stages"][0]["detail"])
    assert "must match resolved document" in detail["errors"][0]["message"]


def test_flat_pipeline_prepare_failure_report_keeps_route_specific_dependency_stages(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def prepare(self, document_id, document_root, config):
            del document_id, document_root, config
            raise RuntimeError("boom")

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "prepare", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert [stage["stage"] for stage in payload["stages"]] == [
        "ingest-sources", "normalize-sources", "compile-structure"
    ]
    detail = json.loads(payload["stages"][1]["detail"])
    assert detail["stages"][1]["result"]["status"] == "skipped"


def test_flat_pipeline_human_output_lists_all_v2_stages(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def prepare(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": False,
                "stages": [
                    {"name": "ingest-sources", "succeeded": True, "result": {}},
                    {"name": "normalize-sources", "succeeded": False, "result": {"error": "bad"}},
                    {"name": "compile-structure", "succeeded": False, "skipped": True, "result": {"status": "skipped"}},
                ],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "prepare"])

    assert result.exit_code == 1
    assert "`ingest-sources`" in result.output
    assert "`normalize-sources`" in result.output
    assert "`compile-structure`" in result.output


def test_flat_pipeline_ingest_reports_v2_construction_failure_when_ingest_dependency_is_missing(
    workspace, monkeypatch
):
    _new_doc()
    calls: list[str] = []

    real_init = Deps.__init__

    def init_without_ingest(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        del self.ingest

    monkeypatch.setattr(Deps, "__init__", init_without_ingest)

    def legacy_run(self, doc_id, template, config, selected, repo_root, strict=False, renderer=None):
        del self, doc_id, template, config, repo_root, strict, renderer
        calls.append(selected)
        raise AssertionError("legacy backend used")

    monkeypatch.setattr("docs.application.pipeline.PipelineService.run_pipeline", legacy_run)

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["schema"] == "docs.sources/v2"
    assert detail["document_id"] == "doc1"
    assert detail["succeeded"] is False
    assert detail["errors"][0]["code"] == "pipeline.v2_construction_failed"
    assert calls == []


@pytest.mark.parametrize("stage_set", ["prep"])
def test_flat_pipeline_prep_uses_v2_operation_boundary(workspace, monkeypatch, stage_set):
    _new_doc()
    calls: list[str] = []

    def operation(name):
        def run():
            calls.append(name)
            return True, name
        return run

    monkeypatch.setattr(
        "docs.application.pipeline.PipelineService._stage_callables",
        lambda *args, **kwargs: {name: operation(name) for name in (
            "doctor", "build-rules", "review-rules", "collect-sources",
            "collect-code-evidence", "collect-issues", "build-ledger",
            "build-sections", "gap-report", "pack-context",
        )},
    )
    monkeypatch.setattr(
        "docs.cli.commands.core_app._source_pipeline_v2",
        lambda deps: (_ for _ in ()).throw(AssertionError("v2 backend used")),
    )

    result = runner.invoke(app, ["pipeline", stage_set, "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["stage_set"] == stage_set
    assert calls[0] == "doctor"


def test_flat_pipeline_all_uses_explicit_v2_adapter_without_implicit_ingest(workspace, monkeypatch):
    _new_doc()
    calls: list[str] = []

    def operation(name):
        def run():
            calls.append(name)
            return True, name
        return run

    monkeypatch.setattr(
        "docs.application.pipeline.PipelineService._stage_callables",
        lambda *args, **kwargs: {name: operation(name) for name in (
            "doctor", "build-rules", "review-rules", "collect-sources",
            "collect-code-evidence", "collect-issues", "build-ledger",
            "build-sections", "gap-report", "pack-context", "review-document",
        )},
    )
    monkeypatch.setattr(
        "docs.cli.commands.core_app._run_v2_assemble",
        lambda deps, resolved, strict, formats: [{
            "stage_set": "assemble",
            "strict": strict,
            "passed": True,
            "stages": [{"stage": "assemble", "ok": True, "duration_s": 0.0, "detail": "v2"}],
        }],
    )

    result = runner.invoke(app, ["pipeline", "all", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["stage_set"] == "all"
    assert [stage["stage"] for stage in payload["stages"]] == [
        "doctor", "build-rules", "review-rules", "collect-sources",
        "collect-code-evidence", "collect-issues", "build-ledger",
        "build-sections", "gap-report", "pack-context", "review-document", "assemble",
    ]
    assert calls[:10] == [
        "doctor", "build-rules", "review-rules", "collect-sources",
        "collect-code-evidence", "collect-issues", "build-ledger",
        "build-sections", "gap-report", "pack-context",
    ]
    assert calls[10] == "review-document"


def test_flat_pipeline_v2_failure_preserves_exit_code_and_summary_shape(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": False,
                "stages": [{"name": "ingest-sources", "succeeded": False, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    assert payload["stages"][0]["ok"] is False


def test_flat_pipeline_v2_strict_is_forwarded_when_supported(workspace, monkeypatch):
    _new_doc()
    strict_calls: list[bool] = []

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config, strict=False):
            del document_id, document_root, config
            strict_calls.append(strict)
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
                "strict_policy": {"requested": True, "applied": True, "mode": "enforced"},
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 0
    assert strict_calls == [True]
    payload = json.loads(result.output)
    assert payload["strict"] is True
    assert payload["strict_policy"]["applied"] is True


def test_flat_pipeline_v2_doc_root_failure_is_structured(workspace, monkeypatch):
    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    deps = SimpleNamespace(
        workspace=SimpleNamespace(doc_root=lambda doc_id: (_ for _ in ()).throw(RuntimeError("root unavailable")))
    )
    resolved = SimpleNamespace(doc_id="doc1", config={})
    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    report = _run_compatible_pipeline(deps, resolved, "ingest", False)

    assert report is not None
    detail = json.loads(report["stages"][0]["detail"])
    assert detail["stages"][0]["result"]["error"] == "v2 source pipeline invocation failed"
    assert detail["errors"][0]["code"] == "pipeline.v2_invocation_failed"


def test_flat_pipeline_v2_does_not_keyword_call_positional_only_strict(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config, strict=False, /):
            del document_id, document_root, config, strict
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["strict_policy"]["mode"] == "advisory"


def test_flat_pipeline_v2_inspects_selected_ingest_callable_not_inner_adapter(
    workspace, monkeypatch
):
    _new_doc()
    strict_calls: list[bool] = []

    class _Adapter:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, sections_dir, assets_dir
            return {"processed": 0, "files": []}

    class _SourcePipeline:
        ingest_service = _Adapter()

        def ingest(self, document_id, document_root, config, *, strict=False):
            del document_id, document_root, config
            strict_calls.append(strict)
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 0
    assert strict_calls == [True]


def test_flat_pipeline_v2_failure_reports_include_document_id(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            raise RuntimeError("boom")

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    detail = json.loads(json.loads(result.output)["stages"][0]["detail"])
    assert detail["document_id"] == "doc1"


def test_flat_pipeline_v2_strict_is_explicitly_advisory_when_unsupported(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["strict"] is True
    strict = payload["strict_policy"]
    assert strict == {
        "requested": True,
        "applied": False,
        "mode": "advisory",
        "warning": "v2 ingest does not expose strict enforcement",
    }


def test_flat_pipeline_v2_checks_strict_support_on_underlying_ingest_adapter(
    workspace, monkeypatch
):
    _new_doc()

    class _UnderlyingIngest:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, sections_dir, assets_dir
            return {}

    class _SourcePipeline:
        ingest_service = _UnderlyingIngest()

        def ingest(self, document_id, document_root, config, strict=False):
            del document_id, document_root, config, strict
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["strict_policy"]["mode"] == "advisory"
    assert payload["warnings"][0]["code"] == "pipeline.strict_advisory"


def test_flat_pipeline_v2_preserves_explicit_strict_policy_from_adapter(
    workspace, monkeypatch
):
    _new_doc()

    class _UnderlyingIngest:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, sections_dir, assets_dir
            return {}

    class _SourcePipeline:
        ingest_service = _UnderlyingIngest()

        def ingest(self, document_id, document_root, config, *, strict=False):
            del document_id, document_root, config, strict
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
                "strict_policy": {"requested": True, "applied": True, "mode": "enforced"},
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["strict_policy"] == {
        "requested": True,
        "applied": True,
        "mode": "enforced",
    }


def test_flat_pipeline_v2_rejects_requested_policy_mismatch_without_masking_evidence(
    workspace, monkeypatch
):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
                "strict_policy": {"requested": True, "applied": False, "mode": "advisory"},
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["strict_policy"] == {
        "requested": True,
        "applied": False,
        "mode": "advisory",
    }
    assert detail["errors"][0]["code"] == "pipeline.malformed_strict_policy"


@pytest.mark.parametrize(
    "strict_policy",
    [
        ["not", "a", "mapping"],
        {"requested": "true", "applied": False, "mode": "advisory"},
        {"requested": False, "applied": 1, "mode": "advisory"},
        {"requested": False, "applied": False, "mode": "not-requested"},
        {"requested": False, "applied": True, "mode": "enforced"},
        {"requested": True, "applied": True, "mode": "advisory"},
        {"requested": True, "applied": False, "mode": "enforced"},
    ],
)
def test_flat_pipeline_v2_rejects_malformed_or_contradictory_strict_policy(
    workspace, monkeypatch, strict_policy
):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
                "strict_policy": strict_policy,
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["errors"][0]["code"] == "pipeline.malformed_strict_policy"


def test_flat_pipeline_v2_signature_inspection_type_error_is_safe(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())
    real_signature = __import__("inspect").signature
    monkeypatch.setattr(
        "docs.cli.commands.core_app.inspect.signature",
        lambda callable_, *args, **kwargs: (
            (_ for _ in ()).throw(TypeError("signature unavailable"))
            if getattr(callable_, "__qualname__", "").endswith("._SourcePipeline.ingest")
            else real_signature(callable_, *args, **kwargs)
        ),
    )

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["strict_policy"]["mode"] == "advisory"
    assert payload["warnings"][0]["code"] == "pipeline.strict_advisory"


def test_flat_pipeline_v2_invocation_type_error_is_structured_failure(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config, *, strict=False):
            del document_id, document_root, config, strict
            raise TypeError("unexpected v2 invocation")

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline invocation failed"}
    assert detail["errors"][0]["code"] == "pipeline.v2_invocation_failed"
    assert "unexpected v2 invocation" in detail["errors"][0]["message"]


def test_flat_pipeline_v2_operation_lookup_failure_is_structured_failure(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        pass

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline operation lookup failed"}
    assert detail["errors"][0]["code"] == "pipeline.v2_operation_lookup_failed"


@pytest.mark.parametrize(
    "report",
    [
        {"succeeded": True, "stages": [{"name": "ingest-sources", "succeeded": True}], "artifacts": []},
        {"schema": "docs.sources/v1", "succeeded": True, "stages": [{"name": "ingest-sources", "succeeded": True}], "artifacts": []},
        {"schema": "docs.sources/v2", "stages": [{"name": "ingest-sources", "succeeded": True}], "artifacts": []},
        {"schema": "docs.sources/v2", "document_id": "doc1", "succeeded": True, "stages": [{"name": "ingest-sources", "succeeded": True}]},
    ],
)
def test_flat_pipeline_v2_rejects_incomplete_report_shape(workspace, monkeypatch, report):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return report

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"


def test_flat_pipeline_v2_empty_report_is_a_structured_failure(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {"schema": "docs.sources/v2", "document_id": "doc1", "succeeded": True, "stages": [], "artifacts": []}

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    assert payload["strict"] is False
    assert len(payload["stages"]) == 1
    assert payload["stages"][0]["stage"] == "ingest-sources"
    assert payload["stages"][0]["ok"] is False
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline returned no stages"}


def test_flat_pipeline_v2_forwards_strict_when_ingest_supports_it(workspace, monkeypatch):
    _new_doc()
    seen: list[bool] = []

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config, *, strict=False):
            seen.append(strict)
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 0
    assert seen == [True]
    assert json.loads(result.output)["strict"] is True


def test_flat_pipeline_v2_reports_advisory_when_ingest_lacks_strict(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["warnings"][0]["code"] == "pipeline.strict_advisory"
    assert "strict" in payload["warnings"][0]["message"]


def test_flat_pipeline_v2_preserves_existing_warnings_when_adding_strict_advisory(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
                "warnings": [{"code": "source.unclassified", "message": "source role is unknown"}],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [warning["code"] for warning in payload["warnings"]] == [
        "source.unclassified",
        "pipeline.strict_advisory",
    ]


def test_flat_pipeline_v2_preserves_upstream_strict_policy_warning(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
                "strict_policy": {
                    "requested": True,
                    "applied": False,
                    "mode": "advisory",
                    "warning": "upstream strict warning",
                },
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--strict", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [warning["code"] for warning in payload["warnings"]] == [
        "pipeline.strict_policy",
        "pipeline.strict_advisory",
    ]
    assert payload["warnings"][0]["message"] == "upstream strict warning"


def test_flat_pipeline_v2_malformed_first_stage_is_structured_failure(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": "yes", "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    assert payload["stages"] == [{
        "stage": "ingest-sources",
        "ok": False,
        "duration_s": 0.0,
        "detail": payload["stages"][0]["detail"],
    }]
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline returned malformed first stage"}
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"


def test_flat_pipeline_v2_malformed_top_level_success_is_structured_failure(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": "yes",
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline returned malformed report"}
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"


def test_flat_pipeline_v2_rejects_non_list_artifacts(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": True}],
                "artifacts": {},
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    detail = json.loads(json.loads(result.output)["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline returned malformed report"}
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"


def test_flat_pipeline_v2_rejects_non_list_stages(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": {"name": "ingest-sources", "succeeded": True},
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    detail = json.loads(json.loads(result.output)["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline returned malformed report"}
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"


@pytest.mark.parametrize(
    "stages",
    [
        [{"succeeded": True}],
        [{"name": "ingest-sources"}],
        [{"name": "ingest-sources", "succeeded": "yes"}],
    ],
)
def test_flat_pipeline_v2_rejects_malformed_stage_records(workspace, monkeypatch, stages):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {"schema": "docs.sources/v2", "document_id": "doc1", "succeeded": True, "stages": stages}

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    detail = json.loads(json.loads(result.output)["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline returned malformed first stage"}
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"


def test_flat_pipeline_v2_rejects_successful_report_with_failed_first_stage(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "ingest-sources", "succeeded": False, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline returned contradictory success values"}
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"


def test_flat_pipeline_v2_rejects_failed_report_with_successful_first_stage(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": False,
                "stages": [{"name": "ingest-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline returned contradictory success values"}
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"


def test_flat_pipeline_v2_requires_ingest_stage_name(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [{"name": "normalize-sources", "succeeded": True, "result": {}}],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline returned malformed first stage"}
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"


def test_flat_pipeline_v2_rejects_extra_stage_records(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return {
                "schema": "docs.sources/v2",
                "document_id": "doc1",
                "succeeded": True,
                "stages": [
                    {"name": "ingest-sources", "succeeded": True, "result": {}},
                    {"name": "normalize-sources", "succeeded": True, "result": {}},
                ],
                "artifacts": [],
            }

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline returned unexpected stage records"}
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"


@pytest.mark.parametrize("malformed_report", [None, [], "invalid"])
def test_flat_pipeline_v2_non_mapping_report_is_structured_failure(
    workspace, monkeypatch, malformed_report
):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return malformed_report

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    detail = json.loads(payload["stages"][0]["detail"])
    assert detail["error"] == {"error": "v2 source pipeline returned malformed report"}
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"


def test_flat_pipeline_v2_returns_structured_failure_when_report_has_no_stages(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            return {"schema": "docs.sources/v2", "document_id": "doc1", "succeeded": True, "stages": [], "artifacts": []}

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    assert len(payload["stages"]) == 1
    assert payload["stages"][0]["ok"] is False
    assert payload["errors"][0]["code"] == "pipeline.empty_v2_report"


@pytest.mark.parametrize(
    "upstream_report",
    [
        {"document_id": "wrong-document", "schema": "docs.sources/v2"},
        {
            "document_id": "wrong-document",
            "schema": "docs.sources/v2",
            "succeeded": True,
            "stages": [],
            "artifacts": [],
        },
    ],
)
def test_flat_pipeline_v2_rejects_malformed_document_ids_without_overwriting_them(
    workspace, monkeypatch, upstream_report
):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            del document_id, document_root, config
            return upstream_report

    monkeypatch.setattr("docs.cli.commands.core_app._source_pipeline_v2", lambda deps: _SourcePipeline())

    result = runner.invoke(app, ["pipeline", "ingest", "--json"])

    assert result.exit_code == 1
    detail = json.loads(json.loads(result.output)["stages"][0]["detail"])
    assert detail["document_id"] == "doc1"
    assert detail["errors"][0]["code"] == "pipeline.malformed_v2_report"
