# tests/unit/cli/test_core_app.py
"""`docs guide` (design.md item B: agent contract, Task 10.4). No workspace
fixture needed -- the guide is static content, not document-scoped."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docs.cli._shared import Deps
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
