"""Graph query routes: the traceability queries and the explicit no-data signal."""

from __future__ import annotations

import json

import pytest

from docs.api.application import ApiApplication
from docs.api.http import Request
from docs.domain.document_graph import (
    DocumentSnapshot,
    FactSnapshot,
    FileEntry,
    RunSnapshot,
    SectionSnapshot,
    project_document_graph,
)
from docs.domain.semantic_graph import SemanticGraph


class _Empty:
    def put(self, item): ...
    def get(self, key=None): return None
    def list(self): return []
    def enqueue(self, job_id, payload): ...


class _Graphs:
    def __init__(self, graph: SemanticGraph) -> None:
        self.graph = graph

    def get(self) -> SemanticGraph:
        return self.graph


def _app(graph: SemanticGraph) -> ApiApplication:
    return ApiApplication(
        run_store=_Empty(), queue=_Empty(), passport_store=_Empty(), artifact_store=_Empty(),
        graph_store=_Empty(), semantic_graph_store=_Graphs(graph),
    )


def _get(app: ApiApplication, query: str) -> dict:
    response = app.dispatch(Request("GET", f"/v2/graph?{query}"))
    assert response.status == 200
    return json.loads(response.body)


GRAPH = project_document_graph([
    DocumentSnapshot(
        doc_id="d",
        sections=(SectionSnapshot("intro", "Intro", 1, "Metodología.", requirements=("metodología", "alcance")),),
        sources=(FileEntry("inbox/a.pdf"),),
        facts=(FactSnapshot("f1", "pendiente", "Hecho", "git"),),
        runs=(RunSnapshot("r", (FileEntry("sections/001-intro.md", sha256="a", current_sha256="b"),), (FileEntry("o.docx"),)),),
    )
])


@pytest.mark.parametrize("style", ["mode={}", "query={}"])
def test_stale_artifacts_and_requirement_coverage_answer_in_both_query_styles(style):
    app = _app(GRAPH)
    stale = _get(app, style.format("stale_artifacts"))
    assert [i["id"] for i in stale["items"]] == ["d/artifact/o.docx"]
    assert stale["no_data"] is False and stale["coverage"]["checked_artifact"] == 1
    coverage = _get(app, style.format("requirement_coverage"))
    row = coverage["items"][0]
    assert row["section"]["id"] == "d/section/intro"
    assert [n["label"] for n in row["missing"]] == ["alcance"]


def test_source_impact_takes_an_id_and_requires_it():
    app = _app(GRAPH)
    payload = _get(app, "query=source_impact&id=d/input/sections/001-intro.md")
    assert [i["id"] for i in payload["items"]] == ["d/artifact/o.docx", "d/section/intro"]
    assert _get(app, "mode=source_impact&source_id=d/input/sections/001-intro.md")["items"] == payload["items"]
    assert app.dispatch(Request("GET", "/v2/graph?query=source_impact")).status == 400


def test_every_query_reports_no_data_when_its_source_kinds_are_absent():
    app = _app(SemanticGraph())
    for name in ("claims_without_evidence", "unused_references", "unmet_requirements", "stale_artifacts", "requirement_coverage"):
        payload = _get(app, f"query={name}")
        assert payload["items"] == [] and payload["no_data"] is True, name
    assert _get(app, "query=artifacts_derived_from_input&id=x")["no_data"] is True
    assert _get(app, "query=findings_affected_by_revision&id=x")["no_data"] is True
    assert _get(app, "query=source_impact&id=x")["no_data"] is True


def test_an_empty_answer_over_real_data_is_not_no_data():
    payload = _get(_app(GRAPH), "query=unused_references")
    assert payload["items"] == [] and payload["no_data"] is True  # the graph has no reference nodes
    payload = _get(_app(GRAPH), "query=unmet_requirements")
    assert payload["no_data"] is False and payload["coverage"] == {"requirement": 2}


def test_raw_node_listing_also_carries_the_no_data_signal():
    assert _get(_app(SemanticGraph()), "kind=claim")["no_data"] is True
    assert _get(_app(GRAPH), "kind=claim")["no_data"] is False
