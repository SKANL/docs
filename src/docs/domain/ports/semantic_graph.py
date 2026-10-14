from __future__ import annotations

from typing import Protocol

from docs.domain.semantic_graph import SemanticGraph


class SemanticGraphReader(Protocol):
    """Read side only: projected graphs are computed on read and never stored."""

    def get(self) -> SemanticGraph | None: ...


class SemanticGraphStore(SemanticGraphReader, Protocol):
    def put(self, graph: SemanticGraph) -> None: ...

