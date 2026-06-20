from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    documents_dir: Path
    templates_dir: Path

    @property
    def registry_path(self) -> Path:
        return self.documents_dir / "registry.json"

    def doc_root(self, doc_id: str) -> Path:
        return self.documents_dir / doc_id
