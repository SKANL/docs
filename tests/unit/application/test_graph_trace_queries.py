"""Traceability queries over a projected document graph: stale outputs, source impact, requirement coverage."""

from __future__ import annotations

from docs.application.graph_queries import GraphQueryService
from docs.domain.document_graph import (
    DocumentSnapshot,
    FactSnapshot,
    FileEntry,
    RunSnapshot,
    SectionSnapshot,
    project_document_graph,
)
from docs.domain.semantic_graph import SemanticGraph


class _Store:
    def __init__(self, graph: SemanticGraph) -> None:
        self.graph = graph

    def get(self) -> SemanticGraph:
        return self.graph


def _service(**overrides) -> GraphQueryService:
    snap = DocumentSnapshot(
        doc_id="d",
        sections=(
            SectionSnapshot("intro", "Intro", 1, "Metodología aplicada.", requirements=("metodología", "alcance")),
            SectionSnapshot("fin", "Fin", 2, "", written=False, requirements=("conclusiones",)),
        ),
        sources=(FileEntry("inbox/a.pdf"),),
        evidence=(FileEntry("ctx.md"),),
        facts=(FactSnapshot("f1", "confirmado", "Hecho", "ctx.md", "ctx.md"),),
        runs=(
            RunSnapshot(
                "r1",
                (
                    FileEntry("sections/001-intro.md", sha256="a", current_sha256="b"),
                    FileEntry("inbox/a.pdf", sha256="c", current_sha256="c"),
                ),
                (FileEntry("out/d.docx"), FileEntry("out/d.pdf")),
            ),
        ),
    )
    snap = DocumentSnapshot(**{**snap.__dict__, **overrides})
    return GraphQueryService(_Store(project_document_graph([snap])))


def test_stale_artifacts_lists_only_artifacts_whose_inputs_changed():
    result = _service().stale_artifacts().value
    assert [n.id for n in result] == ["d/artifact/out/d.docx", "d/artifact/out/d.pdf"]
    fresh = _service(runs=(RunSnapshot("r1", (FileEntry("x", sha256="a", current_sha256="a"),), (FileEntry("o"),)),))
    assert fresh.stale_artifacts().value == ()


def test_source_impact_reaches_artifacts_and_sections_through_the_input_file():
    reached = _service().source_impact("d/source/inbox/a.pdf").value
    assert [n.id for n in reached] == ["d/artifact/out/d.docx", "d/artifact/out/d.pdf"]


def test_source_impact_from_a_section_input_reaches_the_section_and_artifacts():
    reached = _service().source_impact("d/input/sections/001-intro.md").value
    assert [n.id for n in reached] == ["d/artifact/out/d.docx", "d/artifact/out/d.pdf", "d/section/intro"]


def test_source_impact_of_unknown_node_is_empty_not_everything():
    assert _service().source_impact("d/source/missing").value == ()


def test_requirement_coverage_splits_each_section_into_satisfied_and_missing():
    rows = _service().requirement_coverage().value
    by_section = {r.section.id: r for r in rows}
    assert [n.label for n in by_section["d/section/intro"].satisfied] == ["metodología"]
    assert [n.label for n in by_section["d/section/intro"].missing] == ["alcance"]
    assert [n.label for n in by_section["d/section/fin"].missing] == ["conclusiones"]
    assert by_section["d/section/intro"].to_dict()["missing"][0]["label"] == "alcance"


def test_coverage_reports_node_counts_and_no_data_per_query():
    cov = _service().coverage("requirement_coverage").value
    assert cov == {"no_data": False, "counts": {"requirement": 3, "section": 2}}
    empty = GraphQueryService(_Store(SemanticGraph())).coverage("stale_artifacts").value
    assert empty["no_data"] is True
    unchecked = _service(runs=(RunSnapshot("r", (FileEntry("x", sha256="a"),), (FileEntry("o"),)),))
    cov = unchecked.coverage("stale_artifacts").value
    assert cov["no_data"] is True and cov["counts"]["artifact"] == 1 and cov["counts"]["checked_artifact"] == 0


def test_answer_bundles_items_no_data_and_coverage_and_filters_by_document():
    answer = _service().answer("stale_artifacts")
    assert [i["id"] for i in answer.items] == ["d/artifact/out/d.docx", "d/artifact/out/d.pdf"]
    assert answer.no_data is False and answer.coverage["checked_artifact"] == 2
    assert answer.to_payload()["items"] == list(answer.items)
    assert _service().answer("stale_artifacts", document="other").items == ()
    rows = _service().answer("requirement_coverage", document="d").items
    assert [r["section"]["id"] for r in rows] == ["d/section/fin", "d/section/intro"]


def test_answer_reports_unavailable_and_validates_the_query_name_and_subject():
    unavailable = GraphQueryService(None).answer("unused_references")
    assert unavailable.unavailable and unavailable.to_payload() == {
        "items": [], "graph_unavailable": True, "warnings": ["graph unavailable: no semantic graph store configured"]
    }
    import pytest

    with pytest.raises(ValueError, match="unknown graph query"):
        _service().answer("nope")
    with pytest.raises(ValueError, match="requires a subject id"):
        _service().answer("source_impact")
