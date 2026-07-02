from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {"type": "tesina", "title": "Tesina", "sections": [], "section_contracts": {}}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    return tmp_path


def test_doc_new_creates_and_activates(ws):
    result = runner.invoke(app, ["doc", "new", "alpha"])
    assert result.exit_code == 0
    assert "creado desde `tesina`" in result.output
    assert runner.invoke(app, ["doc", "current"]).output.strip() == "alpha"


def test_doc_list_marks_active(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    runner.invoke(app, ["doc", "new", "beta"])
    out = runner.invoke(app, ["doc", "list"]).output
    assert "* beta" in out and "  alpha" in out


def test_doc_show_prints_document_json(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    payload = json.loads(runner.invoke(app, ["doc", "show"]).output)
    assert payload["id"] == "alpha"


def test_doc_use_switches_active(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    runner.invoke(app, ["doc", "new", "beta"])
    runner.invoke(app, ["doc", "use", "alpha"])
    assert runner.invoke(app, ["doc", "current"]).output.strip() == "alpha"


def test_doc_rename(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    result = runner.invoke(app, ["doc", "rename", "alpha", "gamma"])
    assert result.exit_code == 0 and "alpha → gamma" in result.output


def test_doc_delete_requires_yes(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    assert runner.invoke(app, ["doc", "delete", "alpha"]).exit_code == 1
    assert runner.invoke(app, ["doc", "delete", "alpha", "--yes"]).exit_code == 0


def test_doc_list_empty_message(ws):
    result = runner.invoke(app, ["doc", "list"])
    assert "No hay documentos" in result.output
