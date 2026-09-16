from __future__ import annotations

import json
from types import MappingProxyType

import pytest

from docs.domain.semantic_graph import NormalizedSourceRecord, SemanticGraph, SemanticNode, SourceProvenance


def test_semantic_graph_is_immutable_and_has_deterministic_identity() -> None:
    provenance = SourceProvenance("source-1", locator="notes.md", method="parser")
    node = SemanticNode("person-1", "person", "Ada", provenance=(provenance,))
    graph_a = SemanticGraph(nodes=(node,), edges=())
    graph_b = SemanticGraph(nodes=(node,), edges=())

    assert graph_a.canonical_json() == graph_b.canonical_json()
    assert graph_a.graph_id == graph_b.graph_id
    assert json.loads(graph_a.canonical_json()) == graph_a.to_dict()
    assert isinstance(node.attributes, MappingProxyType)


def test_nested_graph_attributes_cannot_be_mutated() -> None:
    node = SemanticNode("n", "thing", "Thing", attributes={"nested": {"value": 1}})

    try:
        node.attributes["nested"]["value"] = 2  # type: ignore[index]
    except TypeError:
        pass
    else:
        raise AssertionError("semantic graph attributes must be immutable")


def test_normalized_source_record_accepts_generic_mapping() -> None:
    record = NormalizedSourceRecord.from_mapping(
        {"source_id": "doc-1", "source_type": "markdown", "content": "Ada"}
    )

    assert record.source_id == "doc-1"
    assert record.to_dict()["content"] == "Ada"


def test_semantic_graph_from_dict_rejects_invalid_shape() -> None:
    with pytest.raises(ValueError, match="graph must be a mapping"):
        SemanticGraph.from_dict([])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="nodes must be a sequence"):
        SemanticGraph.from_dict({"nodes": {"id": "n"}})

    with pytest.raises(ValueError, match="node 0 must be a mapping"):
        SemanticGraph.from_dict({"nodes": ["n"]})

    with pytest.raises(ValueError, match="unsupported semantic graph schema"):
        SemanticGraph.from_dict({"schema": "other", "nodes": [], "edges": []})
