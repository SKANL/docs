"""Deterministic, read-only queries over the semantic graph read model."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from docs.domain.ports.semantic_graph import SemanticGraphReader
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
SECTION_KIND = "section"
SOURCE_KIND = "source"
DOCUMENT_KIND = "document"

SUPPORTS_RELATION = "supports"
AFFECTS_RELATION = "affects"
DERIVED_FROM_RELATION = "derived_from"
REFERENCES_RELATION = "references"
SATISFIES_RELATION = "satisfies"
CONTAINS_RELATION = "contains"

# query -> (kinds whose absence means "no data", extra kinds worth reporting).
# `checked_artifact` is an artifact whose inputs were compared with today's files.
_COVERAGE: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "claims_without_evidence": ((CLAIM_KIND,), (EVIDENCE_KIND,)),
    "findings_affected_by_revision": ((REVISION_KIND,), (FINDING_KIND,)),
    "artifacts_derived_from_input": ((INPUT_KIND,), (ARTIFACT_KIND,)),
    "unused_references": ((REFERENCE_KIND,), ()),
    "unmet_requirements": ((REQUIREMENT_KIND,), ()),
    "stale_artifacts": (("checked_artifact",), (ARTIFACT_KIND, INPUT_KIND)),
    "source_impact": ((SOURCE_KIND, EVIDENCE_KIND, INPUT_KIND), (ARTIFACT_KIND, SECTION_KIND)),
    "requirement_coverage": ((REQUIREMENT_KIND,), (SECTION_KIND,)),
}


@dataclass(frozen=True)
class SectionCoverage:
    section: SemanticNode
    satisfied: tuple[SemanticNode, ...]
    missing: tuple[SemanticNode, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section.to_dict(),
            "satisfied": [n.to_dict() for n in self.satisfied],
            "missing": [n.to_dict() for n in self.missing],
        }


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

    def __init__(self, store: SemanticGraphReader | None) -> None:
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

    def stale_artifacts(self) -> GraphQueryResult[tuple[SemanticNode, ...]]:
        """Return artifacts built from inputs that changed (or vanished) since the build."""
        return self._read(
            lambda graph: self._nodes_by_id(
                graph,
                {n.id for n in graph.nodes if n.kind == ARTIFACT_KIND and n.attributes.get("stale") is True},
            )
        )

    def source_impact(self, node_id: str) -> GraphQueryResult[tuple[SemanticNode, ...]]:
        """Return the artifacts and sections reachable from a source, evidence or input node.

        Walks supports/references/contains forward and derived_from backwards
        (an artifact points at the input it came from). `contains` out of a
        document node is skipped: it would reach everything.
        """

        def query(graph: SemanticGraph) -> tuple[SemanticNode, ...]:
            kinds = {n.id: n.kind for n in graph.nodes}
            if node_id not in kinds:
                return ()
            forward: dict[str, set[str]] = {}
            for edge in graph.edges:
                if edge.relation == DERIVED_FROM_RELATION:
                    forward.setdefault(edge.target, set()).add(edge.source)
                elif edge.relation in {SUPPORTS_RELATION, REFERENCES_RELATION, CONTAINS_RELATION}:
                    if edge.relation == CONTAINS_RELATION and kinds.get(edge.source) == DOCUMENT_KIND:
                        continue
                    forward.setdefault(edge.source, set()).add(edge.target)
            seen = {node_id}
            queue = deque([node_id])
            while queue:
                for nxt in sorted(forward.get(queue.popleft(), ())):
                    if nxt not in seen:
                        seen.add(nxt)
                        queue.append(nxt)
            return self._nodes_by_id(
                graph, {i for i in seen - {node_id} if kinds.get(i) in {ARTIFACT_KIND, SECTION_KIND}}
            )

        return self._read(query)

    def requirement_coverage(self) -> GraphQueryResult[tuple[SectionCoverage, ...]]:
        """Return, per section, which of its requirements are satisfied and which are missing."""

        def query(graph: SemanticGraph) -> tuple[SectionCoverage, ...]:
            satisfied_ids = {e.target for e in graph.edges if e.relation == SATISFIES_RELATION}
            rows = []
            for section in sorted((n for n in graph.nodes if n.kind == SECTION_KIND), key=lambda n: n.id):
                own = [
                    n
                    for n in graph.nodes
                    if n.kind == REQUIREMENT_KIND
                    and f"{n.attributes.get('document')}/{SECTION_KIND}/{n.attributes.get('section')}" == section.id
                ]
                if own:
                    rows.append(
                        SectionCoverage(
                            section,
                            tuple(sorted((n for n in own if n.id in satisfied_ids), key=lambda n: n.id)),
                            tuple(sorted((n for n in own if n.id not in satisfied_ids), key=lambda n: n.id)),
                        )
                    )
            return tuple(rows)

        return self._read(query)

    def coverage(self, query_name: str | None = None) -> GraphQueryResult[dict[str, Any]]:
        """Report what data a query stands on, so "no data" is never read as "nothing wrong"."""

        def query(graph: SemanticGraph) -> dict[str, Any]:
            counts: Counter[str] = Counter(n.kind for n in graph.nodes)
            counts["checked_artifact"] = sum(
                1 for n in graph.nodes if n.kind == ARTIFACT_KIND and "stale" in n.attributes
            )
            if query_name in _COVERAGE:
                subject, context = _COVERAGE[query_name]
                shown = {kind: counts[kind] for kind in (*subject, *context)}
                return {"no_data": not any(counts[k] for k in subject), "counts": dict(sorted(shown.items()))}
            del counts["checked_artifact"]
            return {"no_data": not graph.nodes, "counts": dict(sorted(counts.items()))}

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
