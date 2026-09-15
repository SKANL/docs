from __future__ import annotations

import zipfile
from pathlib import Path

from docs.cli.commands.v2_app import _fallback_structural_audit


def test_structural_fallback_reopens_docx_without_auditor_service(tmp_path: Path) -> None:
    artifact = tmp_path / "document.docx"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")

    passed, detail = _fallback_structural_audit(artifact, "docx")

    assert passed is True
    assert "reopened" in detail


def test_structural_fallback_reports_missing_artifact(tmp_path: Path) -> None:
    passed, detail = _fallback_structural_audit(tmp_path / "missing.pdf", "pdf")

    assert passed is False
    assert "missing" in detail
