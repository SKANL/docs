from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {
    "type": "tesina",
    "title": "Tesina",
    "sections": [],
    "section_contracts": {},
    "context_schema": {
        "topics": [
            {
                "id": "proyecto",
                "title": "Proyecto",
                "required": True,
                "fields": [{"key": "nombre", "label": "Nombre", "required": True}],
            },
        ]
    },
}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    runner.invoke(app, ["doc", "new", "doc1", "--template", "tesina"])
    return tmp_path


def test_context_status_exit_1_when_incomplete(ws):
    result = runner.invoke(app, ["context", "status"])
    assert result.exit_code == 1
    assert "FALTA `proyecto`" in result.output


def test_context_set_then_status_complete(ws):
    assert runner.invoke(app, ["context", "set", "proyecto", "nombre", "Mi App"]).exit_code == 0
    result = runner.invoke(app, ["context", "status"])
    assert result.exit_code == 0
    assert "OK `proyecto`" in result.output


def test_context_set_then_show(ws):
    runner.invoke(app, ["context", "set", "proyecto", "nombre", "Mi App"])
    result = runner.invoke(app, ["context", "show", "proyecto"])
    assert result.exit_code == 0 and "Mi App" in result.output


def test_context_elicit_writes_questionnaire(ws):
    result = runner.invoke(app, ["context", "elicit"])
    assert result.exit_code == 0
    assert result.output.strip().splitlines()[0].endswith("_requests.md")


def test_context_ingest_reports_topics(ws):
    runner.invoke(app, ["context", "elicit"])
    # ingest with an unfilled questionnaire writes nothing
    result = runner.invoke(app, ["context", "ingest"])
    assert result.exit_code == 0 and "Temas ingeridos" in result.output


def test_context_rm(ws):
    runner.invoke(app, ["context", "set", "proyecto", "nombre", "Mi App"])
    result = runner.invoke(app, ["context", "rm", "proyecto"])
    assert result.exit_code == 0 and "eliminado" in result.output
