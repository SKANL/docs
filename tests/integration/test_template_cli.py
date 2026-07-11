# tests/integration/test_template_cli.py
"""Integration coverage for `template init`/`template validate` (design.md
Decision 1c, spec: document-template "Template Skeleton Generation" /
"Template Structural and Completeness Validation"). Exercises the REAL
Typer CLI (not the domain functions directly) so a checked-off task never
ships inert (PR5 CRITICAL lesson): `init` writes a real file `validate`
then reads back."""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from docs.cli.main import app
from docs.domain.models.template import Template

runner = CliRunner()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    documents = tmp_path / "documents"
    templates = tmp_path / "templates"
    documents.mkdir()
    templates.mkdir()
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(documents))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    return templates


def test_init_emits_a_documented_skeleton_covering_every_recognized_block(workspace):
    result = runner.invoke(app, ["template", "init", "mi-tipo"])

    assert result.exit_code == 0
    raw = json.loads((workspace / "mi-tipo.json").read_text(encoding="utf-8"))

    for block in ("apa7", "preliminaries", "format", "paths", "section_contracts", "context_schema", "normative"):
        assert block in raw, f"missing recognized block: {block}"

    # Every declared block parses as a real Template (extra="allow" tolerant).
    Template.model_validate(raw)


def test_optional_blocks_ship_as_documented_placeholders(workspace):
    runner.invoke(app, ["template", "init", "mi-tipo"])
    raw = json.loads((workspace / "mi-tipo.json").read_text(encoding="utf-8"))

    for block in ("apa7", "preliminaries", "format", "paths", "normative"):
        assert "$comment" in raw[block], f"optional block `{block}` is not documented"


def test_validate_on_fresh_init_output_reports_every_todo_as_incomplete(workspace):
    runner.invoke(app, ["template", "init", "mi-tipo"])

    result = runner.invoke(app, ["template", "validate", "mi-tipo"])

    assert result.exit_code != 0
    assert "TODO" in result.output or "incompleto" in result.output.lower()


def test_validate_passes_after_filling_every_todo(workspace):
    runner.invoke(app, ["template", "init", "mi-tipo"])
    path = workspace / "mi-tipo.json"
    raw = json.loads(path.read_text(encoding="utf-8"))

    raw["title"] = "Mi Tipo de Documento"
    raw["sections"][0]["title"] = "Introducción"
    raw["section_contracts"]["introduccion"]["title"] = "Introducción"
    raw["section_contracts"]["introduccion"]["required_content"] = ["objetivo"]
    raw["context_schema"]["topics"][0]["title"] = "Datos del documento"
    raw["context_schema"]["topics"][0]["fields"][0]["label"] = "Nombre"
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    result = runner.invoke(app, ["template", "validate", "mi-tipo"])

    assert result.exit_code == 0


def test_validate_rejects_a_genuinely_invalid_template(workspace):
    (workspace / "roto.json").write_text(
        json.dumps({"type": "roto", "title": "Roto", "format": {"page_margins_cm": {"non_cover": {"top": "no-numero", "right": 2.5, "bottom": 2.5, "left": 2.5}}}}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["template", "validate", "roto"])

    assert result.exit_code != 0


def test_validate_accepts_the_real_reporte_estadia_tic_fixture(workspace, tmp_path):
    import shutil
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "templates" / "reporte-estadia-tic.json"
    shutil.copyfile(fixture, workspace / "reporte-estadia-tic.json")

    result = runner.invoke(app, ["template", "validate", "reporte-estadia-tic"])

    assert result.exit_code == 0, result.output


def test_init_output_is_byte_identical_across_two_runs(workspace):
    first = runner.invoke(app, ["template", "init", "det-check"])
    first_bytes = (workspace / "det-check.json").read_bytes()

    second = runner.invoke(app, ["template", "init", "det-check"])
    second_bytes = (workspace / "det-check.json").read_bytes()

    assert first.exit_code == 0 and second.exit_code == 0
    assert first_bytes == second_bytes
