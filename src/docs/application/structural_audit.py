from __future__ import annotations

from pathlib import Path

from docs.domain.ports.structural_audit_port import StructuralAuditPort
from docs.domain.review import ReviewResult


class StructuralAuditService:
    """Run declarative structural checks; editorial review remains a separate concern."""

    def __init__(self, port: StructuralAuditPort) -> None:
        self.port = port

    def audit(self, artifact_path: Path, rules: dict[str, object]) -> ReviewResult:
        artifact_path = Path(artifact_path)
        if not artifact_path.is_file():
            raise FileNotFoundError(f"No existe artefacto para auditar: {artifact_path}")
        return ReviewResult(self.port.audit(artifact_path, rules))
