from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from docs.domain.ports.semantic_graph import SemanticGraphStore
from docs.domain.semantic_graph import (
    GraphConfidence,
    NormalizedSourceRecord,
    SemanticEdge,
    SemanticGraph,
    SemanticNode,
    SourceProvenance,
    canonical_json,
)


@dataclass(frozen=True)
class GraphProjectionResult:
    graph: SemanticGraph | None
    graph_unavailable: bool = False
    warnings: tuple[str, ...] = ()


class SemanticGraphProjector:
    """Project generic normalized records without making graph availability a hard dependency."""

    def __init__(self, store: SemanticGraphStore | None = None) -> None:
        self._store = store

    def project(self, records: Iterable[NormalizedSourceRecord | Mapping[str, Any]]) -> GraphProjectionResult:
        try:
            normalized = tuple(record if isinstance(record, NormalizedSourceRecord) else NormalizedSourceRecord.from_mapping(record) for record in records)
            nodes: list[SemanticNode] = []
            edges: list[SemanticEdge] = []
            for record in normalized:
                provenance = (SourceProvenance(record.source_id, record.locator),)
                nodes.append(SemanticNode(record.source_id, record.source_type, record.source_id, dict(record.attributes), provenance))
                raw_entities = record.attributes.get("entities", ())
                if isinstance(raw_entities, (list, tuple)):
                    for entity in raw_entities:
                        if not isinstance(entity, Mapping):
                            continue
                        entity_id = str(entity.get("id", "")).strip()
                        label = str(entity.get("label", entity_id)).strip()
                        if not entity_id or not label:
                            continue
                        nodes.append(SemanticNode(entity_id, str(entity.get("kind", "entity")), label, dict(entity.get("attributes", {})), provenance, GraphConfidence(entity.get("evidence", "extracted"), entity.get("confidence", 1.0))))
                raw_edges = record.attributes.get("edges", ())
                if isinstance(raw_edges, (list, tuple)):
                    for edge in raw_edges:
                        if not isinstance(edge, Mapping):
                            continue
                        source = str(edge.get("source", record.source_id)).strip()
                        target = str(edge.get("target", "")).strip()
                        relation = str(edge.get("relation", "related_to")).strip()
                        if source and target and relation:
                            edges.append(SemanticEdge(source, target, relation, provenance, GraphConfidence(edge.get("evidence", "inferred"), edge.get("confidence", 0.5))))
            graph = SemanticGraph(tuple(_merge_nodes(nodes)), tuple(_merge_edges(edges)))
            if self._store is not None:
                try:
                    self._store.put(graph)
                except Exception as exc:  # graph is a best-effort read model
                    return GraphProjectionResult(graph, True, (f"graph persistence unavailable: {exc}",))
            return GraphProjectionResult(graph)
        except Exception as exc:
            return GraphProjectionResult(None, True, (f"graph unavailable: {exc}",))


def _merge_nodes(nodes: Iterable[SemanticNode]) -> list[SemanticNode]:
    merged: dict[str, SemanticNode] = {}
    for node in nodes:
        current = merged.get(node.id)
        if current is None:
            merged[node.id] = node
            continue
        provenance = tuple(
            sorted(
                set(current.provenance + node.provenance),
                key=lambda item: (item.source_id, item.locator, item.method),
            )
        )
        winner = min(
            (current, node),
            key=lambda item: (
                -item.confidence.score,
                -{"ambiguous": 0, "inferred": 1, "extracted": 2}[item.confidence.evidence],
                item.label,
                canonical_json(item.attributes),
                item.kind,
            ),
        )
        merged[node.id] = SemanticNode(
            winner.id,
            winner.kind,
            winner.label,
            winner.attributes,
            provenance,
            winner.confidence,
        )
    return list(merged.values())


def _merge_edges(edges: Iterable[SemanticEdge]) -> list[SemanticEdge]:
    merged: dict[tuple[str, str, str], SemanticEdge] = {}
    for edge in edges:
        key = (edge.source, edge.target, edge.relation)
        current = merged.get(key)
        if current is None:
            merged[key] = edge
            continue
        provenance = tuple(
            sorted(
                set(current.provenance + edge.provenance),
                key=lambda item: (item.source_id, item.locator, item.method),
            )
        )
        winner = min(
            (current, edge),
            key=lambda item: (
                -item.confidence.score,
                -{"ambiguous": 0, "inferred": 1, "extracted": 2}[item.confidence.evidence],
                canonical_json(item.confidence.to_dict()),
            ),
        )
        merged[key] = SemanticEdge(
            edge.source,
            edge.target,
            edge.relation,
            provenance,
            winner.confidence,
        )
    return sorted(merged.values(), key=lambda edge: edge.id)
