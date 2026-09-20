from __future__ import annotations

import pytest

from docs.application.graph_queries import GraphQueryService
from docs.domain.semantic_graph import SemanticEdge, SemanticGraph, SemanticNode


class Store:
    def __init__(self, graph: SemanticGraph | None = None, error: Exception | None = None) -> None:
        self.graph = graph
        self.error = error

    def get(self) -> SemanticGraph | None:
        if self.error is not None:
            raise self.error
        return self.graph


def node(node_id: str, kind: str) -> SemanticNode:
    return SemanticNode(node_id, kind, node_id.upper())


@pytest.fixture
def service() -> GraphQueryService:
    graph = SemanticGraph(
        nodes=(
            node("claim-z", "claim"),
            node("claim-a", "claim"),
            node("evidence-a", "evidence"),
            node("finding-z", "finding"),
            node("finding-a", "finding"),
            node("revision-1", "revision"),
            node("artifact-z", "artifact"),
            node("artifact-a", "artifact"),
            node("input-1", "input"),
            node("reference-z", "reference"),
            node("reference-a", "reference"),
            node("requirement-z", "requirement"),
            node("requirement-a", "requirement"),
        ),
        edges=(
            SemanticEdge("evidence-a", "claim-z", "supports"),
            SemanticEdge("revision-1", "finding-z", "affects"),
            SemanticEdge("artifact-z", "input-1", "derived_from"),
            SemanticEdge("reference-z", "reference-a", "references"),
            SemanticEdge("artifact-a", "requirement-z", "satisfies"),
        ),
    )
    return GraphQueryService(Store(graph))


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("claims_without_evidence", ["claim-a"]),
        ("unused_references", ["reference-z"]),
        ("unmet_requirements", ["requirement-a"]),
    ],
)
def test_domain_queries_return_only_unmatched_nodes_in_id_order(
    service: GraphQueryService, method: str, expected: list[str]
) -> None:
    result = getattr(service, method)()

    assert result.graph_unavailable is False
    assert [item.id for item in result.value] == expected


def test_revision_and_input_queries_follow_direct_domain_edges(service: GraphQueryService) -> None:
    findings = service.findings_affected_by_revision("revision-1")
    artifacts = service.artifacts_derived_from_input("input-1")

    assert [item.id for item in findings.value] == ["finding-z"]
    assert [item.id for item in artifacts.value] == ["artifact-z"]
    assert service.findings_affected_by_revision("missing").value == ()
    assert service.artifacts_derived_from_input("missing").value == ()


def test_domain_query_order_is_independent_of_graph_node_order() -> None:
    nodes = (node("claim-z", "claim"), node("claim-a", "claim"), node("claim-m", "claim"))
    first = SemanticGraph(nodes=nodes, edges=())
    second = SemanticGraph(nodes=tuple(reversed(nodes)), edges=())

    assert [n.id for n in GraphQueryService(Store(first)).claims_without_evidence().value] == [
        "claim-a",
        "claim-m",
        "claim-z",
    ]
    assert [n.id for n in GraphQueryService(Store(second)).claims_without_evidence().value] == [
        "claim-a",
        "claim-m",
        "claim-z",
    ]


@pytest.mark.parametrize("query", ["claims_without_evidence", "unused_references", "unmet_requirements"])
def test_domain_queries_fail_open_when_graph_is_unavailable(query: str) -> None:
    result = getattr(GraphQueryService(Store(error=OSError("read failed"))), query)()

    assert result.graph_unavailable is True
    assert result.value is None
    assert result.warnings == ("graph unavailable: read failed",)


def test_domain_query_with_no_configured_store_is_unavailable() -> None:
    result = GraphQueryService(None).findings_affected_by_revision("revision-1")

    assert result.graph_unavailable is True
    assert result.value is None
    assert result.warnings == ("graph unavailable: no semantic graph store configured",)
