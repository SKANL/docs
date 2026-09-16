from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from docs.domain.semantic_graph import SemanticGraph


class JsonSemanticGraphStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def put(self, graph: SemanticGraph) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(graph.canonical_json() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            _fsync_directory(self.path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self) -> SemanticGraph | None:
        if not self.path.exists():
            return None
        return SemanticGraph.from_dict(json.loads(self.path.read_text(encoding="utf-8")))


class SqliteSemanticGraphStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS semantic_graph (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def put(self, graph: SemanticGraph) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN")
            connection.execute("CREATE TEMP TABLE semantic_graph_stage (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            connection.execute(
                "INSERT INTO semantic_graph_stage (id, payload) VALUES (?, ?)",
                (graph.graph_id, graph.canonical_json()),
            )
            connection.execute("DELETE FROM semantic_graph")
            connection.execute(
                "INSERT INTO semantic_graph (id, payload) SELECT id, payload FROM semantic_graph_stage"
            )

    def get(self) -> SemanticGraph | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT payload FROM semantic_graph LIMIT 1").fetchone()
        return None if row is None else SemanticGraph.from_dict(json.loads(row[0]))


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
