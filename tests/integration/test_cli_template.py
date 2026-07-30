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


# ── PR3: built-in template provisioning (design.md item C) ─────────────────


def test_template_list_available_lists_builtin_names(ws):
    result = runner.invoke(app, ["template", "list", "--available"])
    assert result.exit_code == 0
    assert "documento-generico" in result.output
    assert "reporte-estadia-tic" in result.output


def test_template_list_available_does_not_read_workspace_templates_dir(ws):
    # `--available` lists package data, not `templates_dir` (`tesina` from `ws`).
    result = runner.invoke(app, ["template", "list", "--available"])
    assert "tesina" not in result.output


def test_template_use_copies_builtin_into_workspace(ws):
    result = runner.invoke(app, ["template", "use", "documento-generico"])
    assert result.exit_code == 0, result.output

    from importlib.resources import files

    expected = files("docs.templates.builtin").joinpath("documento-generico.json").read_text(encoding="utf-8")
    written = (ws / "templates" / "documento-generico.json").read_text(encoding="utf-8")
    assert written == expected


def test_template_use_unknown_builtin_errors_cleanly(ws):
    result = runner.invoke(app, ["template", "use", "no-existe"])
    assert result.exit_code != 0


def test_template_use_refuses_clobber_without_force(ws):
    target = ws / "templates" / "documento-generico.json"
    target.write_text('{"type": "documento-generico", "title": "Mine"}', encoding="utf-8")

    result = runner.invoke(app, ["template", "use", "documento-generico"])

    assert result.exit_code != 0
    assert json.loads(target.read_text(encoding="utf-8"))["title"] == "Mine"


def test_template_use_force_overwrites(ws):
    target = ws / "templates" / "documento-generico.json"
    target.write_text('{"type": "documento-generico", "title": "Mine"}', encoding="utf-8")

    result = runner.invoke(app, ["template", "use", "documento-generico", "--force"])

    assert result.exit_code == 0
    assert json.loads(target.read_text(encoding="utf-8"))["title"] == "Documento Genérico"
