from __future__ import annotations

from pathlib import Path
from typing import Protocol

from docs.domain.review import Issue


class StructuralAuditPort(Protocol):
    """Audit document structure from declarative rules, independently of prose review."""

    def audit(self, artifact_path: Path, rules: dict[str, object]) -> list[Issue]: ...
