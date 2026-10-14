"""A real on-disk workspace -> the sidecar API answers the graph queries."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

import pytest

from docs.api.http import Request
from docs.sidecar import SidecarConfig, build_application


@pytest.fixture(autouse=True)
def _canonical_workspace_root(canonical_workspace_root: Path) -> None:
    """Opt this module into canonical temporary workspaces."""


def _write(path: Path, content: str | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


def _build_workspace(root: Path) -> str:
    doc = root / "documents" / "tesis"
    _write(doc / "document.json", {"id": "tesis", "title": "Tesis", "template": "documento-generico"})
    sections = doc / "sections"
    _write(
        sections / "020-introduccion.md",
        "---\nstatus: draft\n---\nEl tema es la calidad. El objetivo es medirla (García, 2020).\n",
    )
    _write(
        sections / "050-referencias.md",
        "# REFERENCIAS\n\nGarcía, J. (2020). Calidad. Editorial.\nLópez, M. (2019). Otro. Editorial.\n",
    )
    evidence = (root / "ctx.md").as_posix()
    _write(
        sections / "source-manifest.json",
        {
            "schema": 1,
            "sources": [{"path": evidence, "type": "approved_context", "classification": "confirmado", "sha256": "h"}],
            "facts": [
                {"classification": "confirmado", "claim": "Respaldado", "source": evidence},
                {"classification": "pendiente", "claim": "Sin respaldo", "source": "context"},
            ],
        },
    )
    _write(
        doc / "runs" / "provenance.json",
        {"runs": {"r1": {"run_id": "r1", "inputs": {"sections/020-introduccion.md": "a"}, "outputs": {"out/tesis.docx": "b"}}}},
    )
    _write(
        sections / "_revisions" / "revision-log.json",
        {"schema": 1, "entries": [
            {"id": "rev1", "section_id": "introduccion", "request": "r", "ts": "t",
             "issues": [{"severity": "error", "message": "falta evidencia", "code": "E1"}]},
            {"section_id": "introduccion", "request": "legacy", "ts": "t0"},
        ]},
    )
    return evidence


def _items(app, workspace_id: str, query: str, **extra: str) -> list[dict]:
    params = "&".join([f"workspace_id={workspace_id}", f"query={query}", *(f"{k}={quote(v, safe='')}" for k, v in extra.items())])
    response = app.application.dispatch(Request("GET", f"/v2/graph?{params}"))
    assert response.status == 200
    payload = json.loads(response.body)
    assert not payload.get("graph_unavailable"), payload
    return payload["items"]


def test_api_answers_graph_queries_from_a_real_workspace(tmp_path: Path) -> None:
    evidence = _build_workspace(tmp_path)
    app = build_application(SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path))
    try:
        ws = app.application.workspace_registry.list()[0]["id"]

        derived = _items(app, ws, "artifacts_derived_from_input", id="tesis/input/sections/020-introduccion.md")
        assert [n["id"] for n in derived] == ["tesis/artifact/out/tesis.docx"]

        unmet = {n["label"] for n in _items(app, ws, "unmet_requirements") if n["id"].startswith("tesis/requirement/introduccion/")}
        assert unmet == {"alcance"}

        unused = [n["label"] for n in _items(app, ws, "unused_references")]
        assert unused == ["López, M. (2019). Otro. Editorial."]

        unsupported = [n["label"] for n in _items(app, ws, "claims_without_evidence")]
        assert unsupported == ["Sin respaldo"]

        findings = _items(app, ws, "findings_affected_by_revision", id="tesis/revision/rev1")
        assert [n["label"] for n in findings] == ["falta evidencia"]
        assert evidence  # path used as the evidence node key
    finally:
        app.shutdown()


def test_reader_caches_until_a_watched_file_changes(tmp_path: Path) -> None:
    import docs.templates
    from docs.composition import open_document_graph_reader

    _build_workspace(tmp_path)
    builtin = Path(docs.templates.__file__).parent / "builtin" / "documento-generico.json"
    _write(tmp_path / "templates" / "documento-generico.json", builtin.read_text(encoding="utf-8"))
    reader = open_document_graph_reader(tmp_path)
    first = reader.get()

    assert reader.get() is first  # unchanged files: same projected object
    section = tmp_path / "documents" / "tesis" / "sections" / "020-introduccion.md"
    section.write_text("El tema, el objetivo y el alcance.", encoding="utf-8")
    os.utime(section, ns=(1, 1_000_000_000_000))  # force a distinct mtime on coarse clocks
    updated = reader.get()

    assert updated is not first
    satisfied = {e.target for e in updated.edges if e.relation == "satisfies" and "introduccion" in e.target}
    assert len(satisfied) == 3  # before the edit only "tema" and "objetivo" matched


def test_reader_returns_an_empty_graph_for_a_workspace_without_documents(tmp_path: Path) -> None:
    from docs.composition import open_document_graph_reader

    graph = open_document_graph_reader(tmp_path).get()

    assert graph.nodes == () and graph.edges == ()
