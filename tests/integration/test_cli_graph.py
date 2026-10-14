"""`docs graph <query>`: the author's view of the same document graph the API serves."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()


def _write(path: Path, content: str | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


@pytest.fixture
def ws(canonical_cli_workspace: Path) -> Path:
    import docs.templates

    root = canonical_cli_workspace
    builtin = Path(docs.templates.__file__).parent / "builtin" / "documento-generico.json"
    _write(root / "templates" / "documento-generico.json", builtin.read_text(encoding="utf-8"))
    for name in ("tesis", "otro"):
        doc = root / "documents" / name
        _write(doc / "document.json", {"id": name, "title": name.title(), "template": "documento-generico"})
        _write(doc / "sections" / "020-introduccion.md", "---\nstatus: draft\n---\nEl tema es la calidad. El objetivo es medirla.\n")
    return root


def test_graph_lists_unmet_requirements_in_spanish(ws):
    result = runner.invoke(app, ["graph", "unmet_requirements"])
    assert result.exit_code == 0, result.output
    assert "Consulta unmet_requirements" in result.output
    assert "alcance" in result.output


def test_graph_filters_by_the_global_doc_option(ws):
    result = runner.invoke(app, ["--doc", "otro", "graph", "unmet_requirements"])
    assert "otro/requirement/" in result.output and "tesis/requirement/" not in result.output


def test_graph_requirement_coverage_splits_satisfied_and_missing(ws):
    result = runner.invoke(app, ["--doc", "tesis", "graph", "requirement_coverage"])
    assert result.exit_code == 0, result.output
    assert "## tesis/section/introduccion" in result.output
    assert "cumplidos: tema, objetivo" in result.output and "faltantes: alcance" in result.output


def test_graph_says_no_data_instead_of_nothing_wrong(canonical_cli_workspace):
    result = runner.invoke(app, ["graph", "claims_without_evidence"])
    assert result.exit_code == 0
    assert "Sin datos" in result.output and "Nada encontrado" not in result.output


def test_graph_says_nothing_found_when_data_exists_and_all_is_fine(ws):
    result = runner.invoke(app, ["graph", "unused_references"])  # sections exist, but no references at all
    assert "Sin datos" in result.output
    result = runner.invoke(app, ["graph", "stale_artifacts"])
    assert "Sin datos" in result.output  # no build ran: no artifact was ever compared


def test_graph_json_matches_the_api_payload_shape(ws):
    result = runner.invoke(app, ["graph", "unmet_requirements", "--json"])
    payload = json.loads(result.output)
    assert payload["no_data"] is False and payload["coverage"]["requirement"] > 0
    assert all(item["kind"] == "requirement" for item in payload["items"])


def test_graph_requires_an_id_for_source_impact_and_rejects_unknown_queries(ws):
    missing = runner.invoke(app, ["graph", "source_impact"])
    assert missing.exit_code == 2 and "--id" in missing.output
    unknown = runner.invoke(app, ["graph", "nope"])
    assert unknown.exit_code == 2 and "Consulta desconocida" in unknown.output


def test_graph_has_help_text():
    result = runner.invoke(app, ["graph", "--help"])
    assert result.exit_code == 0 and "stale_artifacts" in result.output
