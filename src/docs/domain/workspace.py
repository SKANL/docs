from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docs.domain.workspace_format import validate_workspace_layout


@dataclass(frozen=True, init=False)
class Workspace:
    root: Path
    documents_dir: Path
    templates_dir: Path

    def __init__(
        self,
        documents_dir: Path,
        templates_dir: Path,
        root: Path | None = None,
    ) -> None:
        documents_dir = documents_dir.expanduser().resolve()
        templates_dir = templates_dir.expanduser().resolve()
        resolved_root = root.expanduser().resolve() if root is not None else _canonical_parent(
            documents_dir, templates_dir
        )
        validate_workspace_layout(resolved_root, documents_dir, templates_dir)
        object.__setattr__(self, "root", resolved_root)
        object.__setattr__(self, "documents_dir", documents_dir)
        object.__setattr__(self, "templates_dir", templates_dir)

    @property
    def registry_path(self) -> Path:
        return self.documents_dir / "registry.json"

    def doc_root(self, doc_id: str) -> Path:
        return self.documents_dir / doc_id

    def assets_dir(self, doc_id: str) -> Path:
        return self.doc_root(doc_id) / "assets"


def _canonical_parent(documents_dir: Path, templates_dir: Path) -> Path:
    """Compatibility for canonical sibling layouts while callers migrate.

    Inferring a generic common ancestor would accidentally authorize split
    roots.  Only the canonical sibling shape has an unambiguous root.
    """
    if documents_dir.parent != templates_dir.parent:
        raise ValueError("workspace_root_required")
    return documents_dir.parent
