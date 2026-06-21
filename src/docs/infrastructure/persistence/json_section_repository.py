from __future__ import annotations

from pathlib import Path

from docs.domain.markdown_text import split_frontmatter
from docs.domain.workspace import Workspace


class JsonSectionRepository:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def _sections_dir(self, doc_id: str) -> Path:
        return self.workspace.doc_root(doc_id) / "sections"

    def section_path(self, doc_id: str, order: int, section_id: str) -> Path:
        return self._sections_dir(doc_id) / f"{order:03d}-{section_id}.md"

    def sections_dir_exists(self, doc_id: str) -> bool:
        return self._sections_dir(doc_id).exists()

    def section_exists(self, doc_id: str, order: int, section_id: str) -> bool:
        return self.section_path(doc_id, order, section_id).exists()

    def read_section(self, doc_id: str, order: int, section_id: str) -> tuple[dict, str]:
        path = self.section_path(doc_id, order, section_id)
        if not path.exists():
            raise FileNotFoundError(f"Section file does not exist: {path}")
        raw_text = path.read_text(encoding="utf-8")
        return split_frontmatter(raw_text)
