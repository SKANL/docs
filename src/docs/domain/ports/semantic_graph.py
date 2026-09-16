from __future__ import annotations

from typing import Protocol

from docs.domain.semantic_graph import SemanticGraph


class SemanticGraphStore(Protocol):
    def put(self, graph: SemanticGraph) -> None: ...
    def get(self) -> SemanticGraph | None: ...

