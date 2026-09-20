from __future__ import annotations

from docs.application.graph_queries import GraphQueryService
from docs.domain.semantic_graph import SemanticEdge, SemanticGraph, SemanticNode


class Store:
    def __init__(self, graph=None, error=None):
        self.graph = graph
        self.error = error

    def get(self):
        if self.error:
            raise self.error
        return self.graph


def graph() -> SemanticGraph:
    return SemanticGraph(
        nodes=(
            SemanticNode("z", "person", "Zed"),
            SemanticNode("a", "person", "Ada"),
            SemanticNode("b", "place", "Base"),
            SemanticNode("c", "place", "City"),
        ),
        edges=(
            SemanticEdge("a", "b", "lives_in"),
            SemanticEdge("a", "c", "works_in"),
            SemanticEdge("b", "c", "near"),
        ),
    )


def test_find_nodes_and_edges_are_deterministic_and_read_only() -> None:
    service = GraphQueryService(Store(graph()))

    nodes = service.find_nodes(kind="person")
    edges = service.find_edges(relation="lives_in")

    assert [node.id for node in nodes.value] == ["a", "z"]
    assert [(edge.source, edge.target) for edge in edges.value] == [("a", "b")]
    assert service.get_node("a").value.label == "Ada"


def test_neighbors_and_shortest_path_use_stable_ordering() -> None:
    service = GraphQueryService(Store(graph()))

    assert [node.id for node in service.neighbors("a", direction="out").value] == ["b", "c"]
    assert service.shortest_path("a", "c").value == ("a", "c")
    assert service.shortest_path("c", "a").value is None


def test_store_failures_return_graph_unavailable() -> None:
    result = GraphQueryService(Store(error=OSError("read failed"))).find_nodes()

    assert result.graph_unavailable is True
    assert result.value is None
    assert result.warnings == ("graph unavailable: read failed",)


def test_missing_store_or_invalid_direction_is_non_throwing() -> None:
    unavailable = GraphQueryService(None).find_edges()
    unsupported = GraphQueryService(Store(graph())).neighbors("a", direction="sideways")

    assert unavailable.graph_unavailable is True
    assert unsupported.graph_unavailable is False
    assert unsupported.value == ()
