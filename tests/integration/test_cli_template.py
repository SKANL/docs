from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {"type": "tesina", "title": "Plantilla Tesina", "sections": [], "section_contracts": {}}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    return tmp_path


def test_template_list_shows_name_and_title(ws):
    result = runner.invoke(app, ["template", "list"])
    assert result.exit_code == 0
    assert "- tesina: Plantilla Tesina" in result.output


def test_template_list_empty_message(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    (tmp_path / "templates").mkdir()
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(tmp_path / "templates"))
    result = runner.invoke(app, ["template", "list"])
    assert result.exit_code == 0
    assert "No hay plantillas" in result.output


def test_template_show_prints_resolved_json(ws):
    result = runner.invoke(app, ["template", "show", "tesina"])
    payload = json.loads(result.output)
    assert payload["title"] == "Plantilla Tesina"


def test_template_show_unknown_errors_cleanly(ws):
    result = runner.invoke(app, ["template", "show", "nope"])
    assert result.exit_code == 1  # FileNotFoundError -> ERROR path
