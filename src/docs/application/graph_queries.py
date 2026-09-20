"""Deterministic, read-only queries over the semantic graph read model."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from docs.domain.ports.semantic_graph import SemanticGraphStore
from docs.domain.semantic_graph import SemanticEdge, SemanticGraph, SemanticNode

T = TypeVar("T")
Direction = Literal["in", "out", "both"]

CLAIM_KIND = "claim"
EVIDENCE_KIND = "evidence"
FINDING_KIND = "finding"
REVISION_KIND = "revision"
ARTIFACT_KIND = "artifact"
INPUT_KIND = "input"
REFERENCE_KIND = "reference"
REQUIREMENT_KIND = "requirement"

SUPPORTS_RELATION = "supports"
AFFECTS_RELATION = "affects"
DERIVED_FROM_RELATION = "derived_from"
REFERENCES_RELATION = "references"
SATISFIES_RELATION = "satisfies"


@dataclass(frozen=True)
class GraphQueryResult(Generic[T]):
    """A query value, or a stable failure signal when the graph is unavailable."""

    value: T | None = None
    graph_unavailable: bool = False
    warnings: tuple[str, ...] = ()

    @classmethod
    def unavailable(cls, error: Exception) -> GraphQueryResult[T]:
        return cls(graph_unavailable=True, warnings=(f"graph unavailable: {error}",))


class GraphQueryService:
    """Provide deterministic queries without mutating or requiring the graph store."""

    def __init__(self, store: SemanticGraphStore | None) -> None:
        self._store = store

    def find_nodes(
        self, *, kind: str | None = None, label: str | None = None
    ) -> GraphQueryResult[tuple[SemanticNode, ...]]:
        def query(graph: SemanticGraph) -> tuple[SemanticNode, ...]:
            return tuple(
                node
                for node in graph.nodes
                if (kind is None or node.kind == kind)
                and (label is None or node.label == label)
            )

        return self._read(query)

    def find_edges(
        self, *, relation: str | None = None
    ) -> GraphQueryResult[tuple[SemanticEdge, ...]]:
        return self._read(
            lambda graph: tuple(edge for edge in graph.edges if relation is None or edge.relation == relation)
        )

    def get_node(self, node_id: str) -> GraphQueryResult[SemanticNode | None]:
        return self._read(lambda graph: next((node for node in graph.nodes if node.id == node_id), None))

    def neighbors(
        self, node_id: str, *, relation: str | None = None, direction: Direction = "both"
    ) -> GraphQueryResult[tuple[SemanticNode, ...]]:
        if direction not in {"in", "out", "both"}:
            return GraphQueryResult(value=(), warnings=(f"unsupported direction: {direction}",))

        def query(graph: SemanticGraph) -> tuple[SemanticNode, ...]:
            ids: set[str] = set()
            for edge in graph.edges:
                if relation is not None and edge.relation != relation:
                    continue
                if direction in {"out", "both"} and edge.source == node_id:
                    ids.add(edge.target)
                if direction in {"in", "both"} and edge.target == node_id:
                    ids.add(edge.source)
            return tuple(node for node in graph.nodes if node.id in ids)

        return self._read(query)

    def shortest_path(self, source_id: str, target_id: str) -> GraphQueryResult[tuple[str, ...] | None]:
        """Return the lexicographically deterministic shortest directed path of node IDs."""

        def query(graph: SemanticGraph) -> tuple[str, ...] | None:
            node_ids = {node.id for node in graph.nodes}
            if source_id not in node_ids or target_id not in node_ids:
                return None
            adjacency: dict[str, tuple[str, ...]] = {}
            for node_id in node_ids:
                adjacency[node_id] = tuple(
                    sorted({edge.target for edge in graph.edges if edge.source == node_id and edge.target in node_ids})
                )
            queue: deque[tuple[str, ...]] = deque([(source_id,)])
            visited = {source_id}
            while queue:
                path = queue.popleft()
                if path[-1] == target_id:
                    return path
                for neighbor in adjacency[path[-1]]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((*path, neighbor))
            return None

        return self._read(query)

    def claims_without_evidence(self) -> GraphQueryResult[tuple[SemanticNode, ...]]:
        """Return claims without a supporting edge from an evidence node."""

        def query(graph: SemanticGraph) -> tuple[SemanticNode, ...]:
            evidence_ids = {node.id for node in graph.nodes if node.kind == EVIDENCE_KIND}
            supported_claim_ids = {
                edge.target
                for edge in graph.edges
                if edge.relation == SUPPORTS_RELATION and edge.source in evidence_ids
            }
            return self._nodes_by_id(
                graph,
                {
                    node.id
                    for node in graph.nodes
                    if node.kind == CLAIM_KIND and node.id not in supported_claim_ids
                },
            )

        return self._read(query)

    def findings_affected_by_revision(
        self, revision_id: str
    ) -> GraphQueryResult[tuple[SemanticNode, ...]]:
        """Return findings directly affected by the identified revision."""

        def query(graph: SemanticGraph) -> tuple[SemanticNode, ...]:
            revision_ids = {
                node.id
                for node in graph.nodes
                if node.kind == REVISION_KIND and node.id == revision_id
            }
            finding_ids = {
                edge.target
                for edge in graph.edges
                if edge.relation == AFFECTS_RELATION and edge.source in revision_ids
            }
            return self._nodes_by_id(
                graph,
                {
                    node.id
                    for node in graph.nodes
                    if node.kind == FINDING_KIND and node.id in finding_ids
                },
            )

        return self._read(query)

    def artifacts_derived_from_input(
        self, input_id: str
    ) -> GraphQueryResult[tuple[SemanticNode, ...]]:
        """Return artifacts with a direct derivation edge to the identified input."""

        def query(graph: SemanticGraph) -> tuple[SemanticNode, ...]:
            input_ids = {
                node.id
                for node in graph.nodes
                if node.kind == INPUT_KIND and node.id == input_id
            }
            artifact_ids = {
                edge.source
                for edge in graph.edges
                if edge.relation == DERIVED_FROM_RELATION and edge.target in input_ids
            }
            return self._nodes_by_id(
                graph,
                {
                    node.id
                    for node in graph.nodes
                    if node.kind == ARTIFACT_KIND and node.id in artifact_ids
                },
            )

        return self._read(query)

    def unused_references(self) -> GraphQueryResult[tuple[SemanticNode, ...]]:
        """Return reference nodes that have no incoming references edge."""

        def query(graph: SemanticGraph) -> tuple[SemanticNode, ...]:
            referenced_ids = {
                edge.target for edge in graph.edges if edge.relation == REFERENCES_RELATION
            }
            return self._nodes_by_id(
                graph,
                {
                    node.id
                    for node in graph.nodes
                    if node.kind == REFERENCE_KIND and node.id not in referenced_ids
                },
            )

        return self._read(query)

    def unmet_requirements(self) -> GraphQueryResult[tuple[SemanticNode, ...]]:
        """Return requirement nodes that have no incoming satisfaction edge."""

        def query(graph: SemanticGraph) -> tuple[SemanticNode, ...]:
            satisfied_ids = {
                edge.target for edge in graph.edges if edge.relation == SATISFIES_RELATION
            }
            return self._nodes_by_id(
                graph,
                {
                    node.id
                    for node in graph.nodes
                    if node.kind == REQUIREMENT_KIND and node.id not in satisfied_ids
                },
            )

        return self._read(query)

    @staticmethod
    def _nodes_by_id(graph: SemanticGraph, node_ids: set[str]) -> tuple[SemanticNode, ...]:
        return tuple(sorted((node for node in graph.nodes if node.id in node_ids), key=lambda node: node.id))

    def _read(self, query):
        try:
            if self._store is None:
                raise RuntimeError("no semantic graph store configured")
            graph = self._store.get()
            if graph is None:
                raise RuntimeError("no semantic graph available")
            return GraphQueryResult(value=query(graph))
        except Exception as exc:
            return GraphQueryResult.unavailable(exc)
