"""Immutable semantic graph read-model contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

SCHEMA = "docs.semantic-graph/v1"
Evidence = Literal["extracted", "inferred", "ambiguous"]


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize JSON data in one stable, hashable representation."""
    return json.dumps(_thaw(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required_text(value: Any, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _confidence(value: Any) -> float:
    if type(value) not in (int, float) or not 0.0 <= float(value) <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return float(value)


def _evidence(value: Any) -> Evidence:
    if value not in {"extracted", "inferred", "ambiguous"}:
        raise ValueError("evidence must be extracted, inferred, or ambiguous")
    return value


@dataclass(frozen=True)
class GraphConfidence:
    evidence: Evidence = "extracted"
    score: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", _evidence(self.evidence))
        object.__setattr__(self, "score", _confidence(self.score))

    def to_dict(self) -> dict[str, Any]:
        return {"evidence": self.evidence, "score": self.score}


@dataclass(frozen=True)
class SourceProvenance:
    source_id: str
    locator: str = ""
    method: str = "normalized-source"

    def __post_init__(self) -> None:
        _required_text(self.source_id, "source_id")
        if type(self.locator) is not str or type(self.method) is not str:
            raise ValueError("provenance locator and method must be strings")

    def to_dict(self) -> dict[str, str]:
        return {"source_id": self.source_id, "locator": self.locator, "method": self.method}


@dataclass(frozen=True)
class NormalizedSourceRecord:
    """Generic source boundary shared by all graph-producing adapters."""

    source_id: str
    source_type: str
    content: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    locator: str = ""

    def __post_init__(self) -> None:
        _required_text(self.source_id, "source_id")
        _required_text(self.source_type, "source_type")
        if type(self.content) is not str or type(self.locator) is not str:
            raise ValueError("content and locator must be strings")
        object.__setattr__(self, "attributes", _freeze(self.attributes))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> NormalizedSourceRecord:
        return cls(
            source_id=_required_text(value.get("source_id"), "source_id"),
            source_type=_required_text(value.get("source_type", "source"), "source_type"),
            content=value.get("content", ""),
            attributes=value.get("attributes", {}),
            locator=value.get("locator", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "content": self.content,
            "attributes": _thaw(self.attributes),
            "locator": self.locator,
        }


@dataclass(frozen=True)
class SemanticNode:
    id: str
    kind: str
    label: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    provenance: tuple[SourceProvenance, ...] = ()
    confidence: GraphConfidence = field(default_factory=GraphConfidence)

    def __post_init__(self) -> None:
        _required_text(self.id, "id")
        _required_text(self.kind, "kind")
        _required_text(self.label, "label")
        object.__setattr__(self, "attributes", _freeze(self.attributes))
        object.__setattr__(self, "provenance", tuple(self.provenance))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "label": self.label, "attributes": _thaw(self.attributes), "provenance": [p.to_dict() for p in self.provenance], "confidence": self.confidence.to_dict()}


@dataclass(frozen=True)
class SemanticEdge:
    source: str
    target: str
    relation: str
    provenance: tuple[SourceProvenance, ...] = ()
    confidence: GraphConfidence = field(default_factory=GraphConfidence)

    def __post_init__(self) -> None:
        _required_text(self.source, "source")
        _required_text(self.target, "target")
        _required_text(self.relation, "relation")
        object.__setattr__(self, "provenance", tuple(self.provenance))

    @property
    def id(self) -> str:
        return hashlib.sha256(canonical_json(self._identity_dict()).encode()).hexdigest()

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "source": self.source, "target": self.target, "relation": self.relation, "provenance": [p.to_dict() for p in self.provenance], "confidence": self.confidence.to_dict()}


@dataclass(frozen=True)
class SemanticGraph:
    nodes: tuple[SemanticNode, ...] = ()
    edges: tuple[SemanticEdge, ...] = ()
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
            raise ValueError(f"unsupported semantic graph schema: {self.schema}")
        object.__setattr__(self, "nodes", tuple(sorted(self.nodes, key=lambda n: n.id)))
        object.__setattr__(self, "edges", tuple(sorted(self.edges, key=lambda e: e.id)))

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "nodes": [n.to_dict() for n in self.nodes], "edges": [e.to_dict() for e in self.edges]}

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def graph_id(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SemanticGraph:
        if not isinstance(value, Mapping):
            raise ValueError("graph must be a mapping")
        schema = value.get("schema", SCHEMA)
        if schema != SCHEMA:
            raise ValueError(f"unsupported semantic graph schema: {schema}")
        nodes_data = _sequence_field(value, "nodes")
        edges_data = _sequence_field(value, "edges")
        nodes = tuple(_node_from_dict(item, index) for index, item in enumerate(nodes_data))
        edges = tuple(_edge_from_dict(item, index) for index, item in enumerate(edges_data))
        return cls(nodes, edges, schema)


def _sequence_field(value: Mapping[str, Any], name: str) -> Sequence[Any]:
    items = value.get(name, ())
    if isinstance(items, (str, bytes, Mapping)) or not isinstance(items, Sequence):
        raise ValueError(f"{name} must be a sequence")
    return items


def _provenance(data: Any, owner: str, index: int) -> tuple[SourceProvenance, ...]:
    if isinstance(data, (str, bytes, Mapping)) or not isinstance(data, Sequence):
        raise ValueError(f"{owner} {index} provenance must be a sequence")
    try:
        return tuple(SourceProvenance(**item) for item in data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {owner} {index} provenance: {exc}") from exc


def _confidence_data(data: Any, owner: str, index: int) -> GraphConfidence:
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ValueError(f"{owner} {index} confidence must be a mapping")
    try:
        return GraphConfidence(**data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {owner} {index} confidence: {exc}") from exc


def _node_from_dict(item: Any, index: int) -> SemanticNode:
    if not isinstance(item, Mapping):
        raise ValueError(f"node {index} must be a mapping")
    data = dict(item)
    data["provenance"] = _provenance(data.get("provenance", ()), "node", index)
    data["confidence"] = _confidence_data(data.get("confidence"), "node", index)
    try:
        return SemanticNode(**data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid node {index}: {exc}") from exc


def _edge_from_dict(item: Any, index: int) -> SemanticEdge:
    if not isinstance(item, Mapping):
        raise ValueError(f"edge {index} must be a mapping")
    data = dict(item)
    data.pop("id", None)
    data["provenance"] = _provenance(data.get("provenance", ()), "edge", index)
    data["confidence"] = _confidence_data(data.get("confidence"), "edge", index)
    try:
        return SemanticEdge(**data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid edge {index}: {exc}") from exc
