from __future__ import annotations

import json
import sqlite3

import pytest

from docs.domain.semantic_graph import GraphConfidence, SemanticGraph, SemanticNode, SourceProvenance
from docs.infrastructure.semantic_graph import JsonSemanticGraphStore, SqliteSemanticGraphStore


def test_json_and_sqlite_stores_round_trip_canonical_graph(tmp_path) -> None:
    graph = SemanticGraph(
        nodes=(
            SemanticNode(
                "n",
                "thing",
                "Thing",
                provenance=(SourceProvenance("source", "line:1", "parser"),),
                confidence=GraphConfidence("inferred", 0.7),
            ),
        )
    )

    json_store = JsonSemanticGraphStore(tmp_path / "graph.json")
    sqlite_store = SqliteSemanticGraphStore(tmp_path / "graph.sqlite")
    json_store.put(graph)
    sqlite_store.put(graph)

    assert json_store.get() == graph
    assert sqlite_store.get() == graph
    assert (tmp_path / "graph.json").read_text(encoding="utf-8").endswith("\n")


def test_sqlite_store_creates_missing_parent_directory(tmp_path) -> None:
    store = SqliteSemanticGraphStore(tmp_path / "nested" / "graph.sqlite")

    store.put(SemanticGraph(nodes=(SemanticNode("n", "thing", "Thing"),)))

    assert store.get() is not None


def test_sqlite_store_preserves_previous_graph_when_replacement_insert_fails(tmp_path) -> None:
    path = tmp_path / "graph.sqlite"
    store = SqliteSemanticGraphStore(path)
    previous = SemanticGraph(nodes=(SemanticNode("old", "thing", "Old"),))
    replacement = SemanticGraph(nodes=(SemanticNode("new", "thing", "New"),))
    store.put(previous)

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_graph_insert
            BEFORE INSERT ON semantic_graph
            BEGIN
                SELECT RAISE(ABORT, 'replacement rejected');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="replacement rejected"):
        store.put(replacement)

    assert store.get() == previous


def test_json_store_cleans_temporary_file_when_replace_fails(tmp_path, monkeypatch) -> None:
    path = tmp_path / "graph.json"
    store = JsonSemanticGraphStore(path)

    def fail_replace(self, target):
        raise OSError("replace failed")

    monkeypatch.setattr(type(path), "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.put(SemanticGraph())

    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_json_store_round_trips_provenance_and_confidence(tmp_path) -> None:
    graph = SemanticGraph(
        nodes=(
            SemanticNode(
                "n",
                "thing",
                "Thing",
                provenance=(SourceProvenance("source", "line:1", "parser"),),
                confidence=GraphConfidence("inferred", 0.7),
            ),
        )
    )

    store = JsonSemanticGraphStore(tmp_path / "graph.json")
    store.put(graph)

    assert json.loads((tmp_path / "graph.json").read_text(encoding="utf-8")) == graph.to_dict()
    assert store.get() == graph
