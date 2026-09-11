from __future__ import annotations

from pathlib import Path

from docs.application.structural_audit import StructuralAuditService
from docs.domain.review import Issue


class RecordingStructuralAudit:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, dict[str, object]]] = []

    def audit(self, artifact_path: Path, rules: dict[str, object]) -> list[Issue]:
        self.calls.append((artifact_path, rules))
        return [Issue("warning", "missing metadata", "metadata.missing")]


def test_structural_audit_service_keeps_editorial_audit_separate(tmp_path):
    artifact = tmp_path / "report.docx"
    artifact.write_bytes(b"content")
    port = RecordingStructuralAudit()
    rules = {"headings": ["INTRODUCTION"], "metadata": {"title": True}}

    result = StructuralAuditService(port).audit(artifact, rules)

    assert result.passed is True
    assert result.issues[0].code == "metadata.missing"
    assert port.calls == [(artifact, rules)]


def test_structural_audit_service_rejects_missing_artifact(tmp_path):
    try:
        StructuralAuditService(RecordingStructuralAudit()).audit(tmp_path / "missing.docx", {})
    except FileNotFoundError as error:
        assert "No existe artefacto" in str(error)
    else:
        raise AssertionError("expected missing artifact to fail")
