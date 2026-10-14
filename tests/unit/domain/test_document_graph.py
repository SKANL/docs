"""The document-graph projector: pure snapshot -> SemanticGraph."""

from __future__ import annotations

import random

from docs.application.graph_queries import GraphQueryService
from docs.domain.document_graph import (
    DocumentSnapshot,
    FactSnapshot,
    FileEntry,
    RevisionSnapshot,
    RunSnapshot,
    SectionSnapshot,
    project_document_graph,
)

BODY = "Se usa la metodología ágil (García, 2020).\n\n# REFERENCIAS\n\nGarcía, J. (2020). Agile. X.\nLópez, M. (2019). Otro. Y.\n"
ISSUE = {"severity": "error", "message": "falta evidencia", "code": "E1", "dimension": "evidence"}


def snapshot(doc: str = "doc") -> DocumentSnapshot:
    return DocumentSnapshot(
        doc_id=doc,
        title="Doc",
        sections=(
            SectionSnapshot("intro", "Intro", 1, BODY, requirements=("metodología", "alcance")),
            SectionSnapshot("fin", "Fin", 2, "", written=False, requirements=("conclusiones",)),
        ),
        sources=(FileEntry("inbox/a.pdf", type="pdf"),),
        evidence=(FileEntry("/ctx/a.md", type="approved_context", classification="confirmado"),),
        facts=(
            FactSnapshot("f1", "confirmado", "Hecho A", "/ctx/a.md", "/ctx/a.md"),
            FactSnapshot("f2", "pendiente", "Hecho B", "git"),
        ),
        runs=(
            RunSnapshot("r1", inputs=(FileEntry("sections/001-intro.md", sha256="h1"),),
                        outputs=(FileEntry("out/doc.docx", sha256="h2"),)),
        ),
        revisions=(RevisionSnapshot("rev1", "intro", "cambio", "t1", issues=(ISSUE,)),),
    )


def ids(graph, kind):
    return sorted(n.id for n in graph.nodes if n.kind == kind)


def edges(graph, relation):
    return sorted((e.source, e.target) for e in graph.edges if e.relation == relation)


class _Store:
    def __init__(self, graph):
        self.graph = graph

    def get(self):
        return self.graph

    def put(self, graph):
        self.graph = graph


def test_node_ids_are_namespaced_by_document_and_kind():
    graph = project_document_graph([snapshot()])
    assert ids(graph, "document") == ["doc/document/doc"]
    assert ids(graph, "section") == ["doc/section/fin", "doc/section/intro"]
    assert ids(graph, "input") == ["doc/input/sections/001-intro.md"]
    assert ids(graph, "artifact") == ["doc/artifact/out/doc.docx"]
    assert ids(graph, "revision") == ["doc/revision/rev1"]
    assert len(ids(graph, "claim")) == 2 and len(ids(graph, "finding")) == 1


def test_supports_links_evidence_to_claims_through_source_path_only():
    graph = project_document_graph([snapshot()])
    assert edges(graph, "supports") == [("doc/evidence//ctx/a.md", "doc/claim/f1")]
    unsupported = GraphQueryService(_Store(graph)).claims_without_evidence().value
    assert [n.id for n in unsupported] == ["doc/claim/f2"]


def test_requirements_are_satisfied_by_section_text():
    graph = project_document_graph([snapshot()])
    svc = GraphQueryService(_Store(graph))
    unmet = {n.label for n in svc.unmet_requirements().value}
    assert unmet == {"alcance", "conclusiones"}
    assert [t for _, t in edges(graph, "satisfies")] == [
        n.id for n in graph.nodes if n.kind == "requirement" and n.label == "metodología"
    ]


def test_references_are_matched_to_sections_by_author_key():
    graph = project_document_graph([snapshot()])
    unused = GraphQueryService(_Store(graph)).unused_references().value
    assert [n.label for n in unused] == ["López, M. (2019). Otro. Y."]
    assert [s for s, _ in edges(graph, "references")] == ["doc/section/intro"]


def test_revision_links_to_findings_and_sections():
    graph = project_document_graph([snapshot()])
    svc = GraphQueryService(_Store(graph))
    found = svc.findings_affected_by_revision("doc/revision/rev1").value
    assert [n.label for n in found] == ["falta evidencia"]
    assert edges(graph, "revises") == [("doc/revision/rev1", "doc/section/intro")]


def test_artifacts_derive_from_inputs():
    graph = project_document_graph([snapshot()])
    out = GraphQueryService(_Store(graph)).artifacts_derived_from_input("doc/input/sections/001-intro.md").value
    assert [n.id for n in out] == ["doc/artifact/out/doc.docx"]


def test_projection_is_deterministic_and_documents_do_not_collide():
    snap = snapshot()
    shuffled = DocumentSnapshot(
        **{**snap.__dict__, "facts": tuple(reversed(snap.facts)), "sections": tuple(reversed(snap.sections))}
    )
    assert project_document_graph([snap]).graph_id == project_document_graph([shuffled]).graph_id
    random.seed(1)
    both = project_document_graph([snapshot("a"), snapshot("b")])
    assert len(ids(both, "document")) == 2
    assert len({n.id for n in both.nodes}) == len(both.nodes)


def test_legacy_revision_without_issues_projects_without_findings():
    snap = DocumentSnapshot(doc_id="d", title="d", revisions=(RevisionSnapshot("r", "x", "q", "t"),))
    graph = project_document_graph([snap])
    assert ids(graph, "finding") == [] and ids(graph, "revision") == ["d/revision/r"]
