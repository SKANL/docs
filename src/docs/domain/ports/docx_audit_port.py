from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from docs.domain.review import Issue


class DocxAuditPort(Protocol):
    def audit(self, docx_path: Path, config: dict[str, Any], strict: bool) -> list[Issue]: ...
    def list_parts(self, docx_path: Path, prefix: str) -> list[str]: ...
    def read_xml(self, docx_path: Path, part_name: str) -> str: ...
