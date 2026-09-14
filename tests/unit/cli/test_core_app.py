# tests/unit/cli/test_core_app.py
"""`docs guide` (design.md item B: agent contract, Task 10.4). No workspace
fixture needed -- the guide is static content, not document-scoped."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from docs.application.flat_pipeline_compatibility import route_for
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


def _fake_run_pipeline(seen_formats):
    def run_pipeline(self, doc_id, template, config, stage_set, repo_root, strict=False, renderer=None):
        seen_formats.append(renderer.output_format)
        return {"stage_set": stage_set, "strict": strict, "passed": True, "stages": []}

    return run_pipeline


def test_deps_registers_the_html_renderer(workspace):
    assert "html" in Deps().renderers
    assert Deps().renderers["html"].output_format == "html"


def test_deps_registers_the_pdf_renderer(workspace):
    assert "pdf" in Deps().renderers
    assert Deps().renderers["pdf"].output_format == "pdf"


def test_deps_registers_named_legacy_pipeline_service(workspace):
    deps = Deps()

    assert deps.legacy_pipeline is not deps.pipeline
    assert deps.legacy_pipeline._pipeline is deps.pipeline


def test_pipeline_format_pdf_selects_the_pdf_renderer(workspace, monkeypatch):
    _new_doc()
    seen_formats: list[str] = []
    monkeypatch.setattr("docs.application.pipeline.PipelineService.run_pipeline", _fake_run_pipeline(seen_formats))

    result = runner.invoke(app, ["pipeline", "assemble", "--format", "pdf"])

    assert result.exit_code == 0
    assert seen_formats == ["pdf"]


def test_pipeline_format_html_selects_the_html_renderer(workspace, monkeypatch):
    _new_doc()
    seen_formats: list[str] = []
    monkeypatch.setattr("docs.application.pipeline.PipelineService.run_pipeline", _fake_run_pipeline(seen_formats))

    result = runner.invoke(app, ["pipeline", "assemble", "--format", "html"])

    assert result.exit_code == 0
    assert seen_formats == ["html"]


def test_pipeline_format_is_repeatable_and_builds_each_requested_format(workspace, monkeypatch):
    _new_doc()
    seen_formats: list[str] = []
    monkeypatch.setattr("docs.application.pipeline.PipelineService.run_pipeline", _fake_run_pipeline(seen_formats))

    result = runner.invoke(app, ["pipeline", "assemble", "--format", "html", "--format", "docx"])

    assert result.exit_code == 0
    assert seen_formats == ["html", "docx"]


def test_pipeline_no_format_flag_keeps_the_config_driven_docx_default(workspace, monkeypatch):
    # No flag -- today's behavior: the renderer comes from `output.format` in
    # the merged template/document config (default "docx"), same as before
    # `--format` existed. Never hardcode "docx" as the CLI default; that would
    # silently ignore an explicit `output.format` in a template's config.
    _new_doc()
    seen_formats: list[str] = []
    monkeypatch.setattr("docs.application.pipeline.PipelineService.run_pipeline", _fake_run_pipeline(seen_formats))

    result = runner.invoke(app, ["pipeline", "assemble"])

    assert result.exit_code == 0
    assert seen_formats == ["docx"]


def test_pipeline_json_output_stays_a_single_object_for_one_format(workspace, monkeypatch):
    # Backward compatibility: existing callers parse a single JSON object
    # (`json.loads(result.output)`), not a list -- must not change shape when
    # only one format is built (the default, unflagged path).
    _new_doc()
    monkeypatch.setattr(
        "docs.application.pipeline.PipelineService.run_pipeline",
        _fake_run_pipeline([]),
    )

    result = runner.invoke(app, ["pipeline", "assemble", "--json"])

    payload = json.loads(result.output)
    assert isinstance(payload, dict)
    assert payload["passed"] is True


def test_pipeline_json_output_is_a_list_when_multiple_formats_requested(workspace, monkeypatch):
    _new_doc()
    monkeypatch.setattr(
        "docs.application.pipeline.PipelineService.run_pipeline",
        _fake_run_pipeline([]),
    )

    result = runner.invoke(app, ["pipeline", "assemble", "--format", "html", "--format", "docx", "--json"])

    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 2


def test_flat_pipeline_policy_routes_only_ingest_to_v2():
    assert route_for("ingest") is not None
    assert route_for("prep") is None
    assert route_for("assemble") is None
    assert route_for("all") is None
    assert route_for("unsupported") is None


def test_flat_pipeline_ingest_preserves_legacy_summary_shape_and_uses_v2(workspace, monkeypatch):
    _new_doc()
    calls: list[tuple[str, str]] = []

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            calls.append((document_id, str(document_root)))
            return {
                "schema": "docs.sources/v2",
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


@pytest.mark.parametrize("stage_set", ["prep", "assemble", "all"])
def test_flat_pipeline_unsupported_stage_sets_stay_on_legacy_backend(workspace, monkeypatch, stage_set):
    _new_doc()
    calls: list[str] = []

    def legacy_run(self, doc_id, template, config, selected, repo_root, strict=False, renderer=None):
        calls.append(selected)
        return {"stage_set": selected, "strict": strict, "passed": True, "stages": []}

    monkeypatch.setattr("docs.application.pipeline.PipelineService.run_pipeline", legacy_run)
    monkeypatch.setattr(
        "docs.cli.commands.core_app._source_pipeline_v2",
        lambda deps: (_ for _ in ()).throw(AssertionError("v2 backend used")),
    )

    result = runner.invoke(app, ["pipeline", stage_set, "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["stage_set"] == stage_set
    assert calls == [stage_set]


def test_flat_pipeline_v2_failure_preserves_exit_code_and_summary_shape(workspace, monkeypatch):
    _new_doc()

    class _SourcePipeline:
        def ingest(self, document_id, document_root, config):
            return {
                "schema": "docs.sources/v2",
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
        {"schema": "docs.sources/v2", "succeeded": True, "stages": [{"name": "ingest-sources", "succeeded": True}]},
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
            return {"schema": "docs.sources/v2", "succeeded": True, "stages": [], "artifacts": []}

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
            return {"schema": "docs.sources/v2", "succeeded": True, "stages": stages}

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
            return {"schema": "docs.sources/v2", "succeeded": True, "stages": [], "artifacts": []}

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
def test_flat_pipeline_v2_forces_selected_document_id_on_malformed_reports(
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
