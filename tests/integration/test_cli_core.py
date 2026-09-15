# tests/integration/test_cli_core.py
from __future__ import annotations

import json

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


def test_doctor_json_exposes_deterministic_v2_capability_diagnostics(workspace):
    _new_doc()
    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code in (0, 2)
    payload = json.loads(result.output)
    assert list(payload["capabilities"]) == sorted(payload["capabilities"])
    assert list(payload["capability_diagnostics"]) == sorted(payload["capability_diagnostics"])
    assert set(payload["capabilities"]) == set(payload["capability_diagnostics"])
    assert {"available", "path"} <= set(payload["capabilities"]["pillow"])
    assert {
        "available", "path", "version", "diagnostic", "policy"
    } <= set(payload["capability_diagnostics"]["pillow"])


def test_doctor_json_reports_unregistered_output_format_without_crashing(workspace):
    invalid_template = dict(_TEMPLATE, output={"format": "epub"})
    (workspace / "templates" / "tesina.json").write_text(
        json.dumps(invalid_template), encoding="utf-8"
    )
    _new_doc()

    result = runner.invoke(app, ["doctor", "--json"])

    assert not isinstance(result.exception, ValueError)
    assert result.exit_code in (0, 2)
    payload = json.loads(result.output)
    assert isinstance(payload.get("capability_diagnostics"), dict)


def test_resolve_context_errors_when_no_active_document(workspace):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "No hay documento activo" in (result.output + str(result.exception or ""))












# --- `docs explain`: the review loop's vocabulary, on the tool surface --------


def test_explain_without_argument_prints_the_whole_issue_code_catalog():
    # `docs explain` must work with NO workspace: an agent hitting an unknown
    # code needs the answer wherever it is standing.
    result = runner.invoke(app, ["explain"])

    assert result.exit_code == 0
    assert "content.pending_not_allowed" in result.stdout
    assert "coherence.duration_mismatch" in result.stdout


def test_explain_a_known_code_prints_meaning_and_fix():
    result = runner.invoke(app, ["explain", "apa.quote_without_locator"])

    assert result.exit_code == 0
    assert "Qué significa" in result.stdout
    assert "Cómo se resuelve" in result.stdout
    assert "localizador" in result.stdout


def test_explain_an_unknown_code_suggests_near_matches_and_exits_nonzero():
    result = runner.invoke(app, ["explain", "content.pending"])

    assert result.exit_code == 2
    assert "content.pending_not_allowed" in result.stdout


