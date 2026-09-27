from __future__ import annotations

from typing import Protocol

from docs.domain.runtime_records import Graph


class GraphStore(Protocol):
    def put(self, graph: Graph) -> None: ...
    def get(self) -> Graph: ...
