from __future__ import annotations

from docs.application.semantic_graph import SemanticGraphProjector
from docs.domain.semantic_graph import NormalizedSourceRecord, SourceProvenance


def test_projector_projects_entities_and_relationships_deterministically() -> None:
    records = [NormalizedSourceRecord("source", "markdown", attributes={"entities": [{"id": "ada", "kind": "person", "label": "Ada"}], "edges": [{"target": "ada", "relation": "mentions"}]})]

    result = SemanticGraphProjector().project(records)

    assert result.graph_unavailable is False
    assert result.graph is not None
    assert [node.id for node in result.graph.nodes] == ["ada", "source"]
    assert result.graph.edges[0].relation == "mentions"


def test_projector_reports_persistence_failure_without_failing_projection() -> None:
    class BrokenStore:
        def put(self, graph):
            raise OSError("offline")

        def get(self):
            return None

    result = SemanticGraphProjector(BrokenStore()).project([{"source_id": "source", "source_type": "text"}])

    assert result.graph is not None
    assert result.graph_unavailable is True
    assert "offline" in result.warnings[0]


def test_projector_merges_duplicate_nodes_without_losing_provenance_or_confidence() -> None:
    records = [
        NormalizedSourceRecord(
            "source-a",
            "markdown",
            locator="a.md",
            attributes={
                "entities": [
                    {"id": "ada", "kind": "person", "label": "Ada", "evidence": "inferred", "confidence": 0.4}
                ]
            },
        ),
        NormalizedSourceRecord(
            "source-b",
            "markdown",
            locator="b.md",
            attributes={
                "entities": [
                    {"id": "ada", "kind": "person", "label": "Ada", "evidence": "extracted", "confidence": 0.9}
                ]
            },
        ),
    ]

    result = SemanticGraphProjector().project(records)

    assert result.graph is not None
    ada = next(node for node in result.graph.nodes if node.id == "ada")
    assert ada.provenance == (
        SourceProvenance("source-a", "a.md"),
        SourceProvenance("source-b", "b.md"),
    )
    assert ada.confidence.evidence == "extracted"
    assert ada.confidence.score == 0.9


def test_projector_merges_equal_confidence_duplicates_independent_of_record_order() -> None:
    first = NormalizedSourceRecord(
        "source-a",
        "markdown",
        locator="a.md",
        attributes={
            "entities": [
                {"id": "ada", "kind": "person", "label": "Zelda", "attributes": {"z": 1}, "evidence": "inferred", "confidence": 0.8}
            ]
        },
    )
    second = NormalizedSourceRecord(
        "source-b",
        "markdown",
        locator="b.md",
        attributes={
            "entities": [
                {"id": "ada", "kind": "person", "label": "Ada", "attributes": {"a": 1}, "evidence": "inferred", "confidence": 0.8}
            ]
        },
    )

    forward = SemanticGraphProjector().project([first, second]).graph
    reverse = SemanticGraphProjector().project([second, first]).graph

    assert forward is not None
    assert reverse is not None
    assert forward.canonical_json() == reverse.canonical_json()
    ada = next(node for node in forward.nodes if node.id == "ada")
    assert ada.label == "Ada"
    assert dict(ada.attributes) == {"a": 1}


def test_projector_merges_duplicate_edges_by_semantic_identity() -> None:
    records = [
        NormalizedSourceRecord(
            "source-a", "markdown", locator="a.md",
            attributes={"edges": [{"source": "ada", "target": "bob", "relation": "knows", "confidence": 0.4}]},
        ),
        NormalizedSourceRecord(
            "source-b", "markdown", locator="b.md",
            attributes={"edges": [{"source": "ada", "target": "bob", "relation": "knows", "evidence": "extracted", "confidence": 0.9}]},
        ),
    ]

    result = SemanticGraphProjector().project(records)

    assert result.graph is not None
    assert len(result.graph.edges) == 1
    edge = result.graph.edges[0]
    assert edge.provenance == (SourceProvenance("source-a", "a.md"), SourceProvenance("source-b", "b.md"))
    assert edge.confidence.evidence == "extracted"
    assert edge.confidence.score == 0.9


def test_projector_duplicate_edges_are_reversal_and_identity_order_independent() -> None:
    first = NormalizedSourceRecord(
        "source-a", "markdown", locator="a.md",
        attributes={"edges": [{"source": "ada", "target": "bob", "relation": "knows", "confidence": 0.8}]},
    )
    second = NormalizedSourceRecord(
        "source-b", "markdown", locator="b.md",
        attributes={"edges": [{"source": "ada", "target": "bob", "relation": "knows", "confidence": 0.8}]},
    )

    forward = SemanticGraphProjector().project([first, second]).graph
    reverse = SemanticGraphProjector().project([second, first]).graph

    assert forward is not None and reverse is not None
    assert forward.canonical_json() == reverse.canonical_json()
    assert forward.edges[0].id == reverse.edges[0].id
