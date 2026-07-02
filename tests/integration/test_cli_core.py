# tests/integration/test_cli_core.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docs.cli._shared import Deps
from docs.cli.main import app

runner = CliRunner()

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
    # DEVIATION from the plan's literal `_new_doc` (which invokes `docs doc
    # new`): the `doc` command group is Task 6's scope, not Task 1's, and does
    # not exist yet when this suite runs. Create the document directly through
    # the already-shipped DocumentService instead of shelling out to a CLI
    # command that doesn't exist yet. `DocumentService.create` also marks the
    # new document active (see
    # test_document_service.py::test_create_builds_workspace_and_sets_active).
    Deps().documents.create(doc_id, "tesina")


def test_stamp_prints_iso_timestamp(workspace):
    result = runner.invoke(app, ["stamp"])
    assert result.exit_code == 0
    assert "T" in result.output.strip()  # ISO 8601


def test_doctor_returns_exit_2_when_checks_fail(workspace):
    _new_doc()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code in (0, 2)  # env-dependent (pandoc/gh), never crash
    assert "Doctor del arnés" in result.output


def test_doctor_json_emits_dict(workspace):
    _new_doc()
    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.output)
    assert "passed" in payload and "checks" in payload


def test_resolve_context_errors_when_no_active_document(workspace):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "No hay documento activo" in (result.output + str(result.exception or ""))


def test_history_reports_empty_when_no_runs(workspace):
    _new_doc()
    result = runner.invoke(app, ["history"])
    assert result.exit_code == 0
    assert "Sin corridas" in result.output


def test_pipeline_prep_runs_and_reports_a_summary(workspace, monkeypatch):
    _new_doc()
    monkeypatch.setattr("shutil.which", lambda name: None)  # gh unavailable
    result = runner.invoke(app, ["pipeline", "prep"])
    assert result.exit_code in (0, 1)
    assert "Pipeline `prep`" in result.output


def test_pipeline_unknown_stage_set_errors_cleanly(workspace):
    _new_doc()
    result = runner.invoke(app, ["pipeline", "bogus"])
    assert result.exit_code == 1
    assert "Conjunto de etapas desconocido" in (result.output + str(result.exception or ""))
