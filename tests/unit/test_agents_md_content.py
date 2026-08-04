# tests/unit/test_agents_md_content.py
"""Agent-contract coverage (spec: agent-contract "Shipped AGENTS.md", MODIFIED
Requirement): AGENTS.md must document the doc revise semantic-edit loop,
output-format selection (docx/html/pdf) including the PDF non-determinism
caveat, and the lifecycle/build-version fields surfaced by `doc status`.
Fast content check on the repo-root file directly (no wheel build) --
tests/unit/test_agents_md_packaging.py already covers the packaged-copy byte
identity separately."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_MD = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_documents_format_selection_and_pdf_non_determinism_caveat():
    assert "--format" in AGENTS_MD
    assert "html" in AGENTS_MD and "pdf" in AGENTS_MD
    assert "non-byte-deterministic" in AGENTS_MD
    assert "soffice" in AGENTS_MD or "LibreOffice" in AGENTS_MD


def test_documents_doc_revise_loop():
    assert "doc revise" in AGENTS_MD
    assert "revision-log" in AGENTS_MD or "diff" in AGENTS_MD


def test_documents_lifecycle_and_build_version():
    assert "mark-final" in AGENTS_MD
    assert "lifecycle" in AGENTS_MD
    assert "build_version" in AGENTS_MD


def test_documents_second_builtin_template():
    assert "technical-report-srs" in AGENTS_MD


def test_documents_visual_specs_authoring_format():
    assert "visual-specs.json" in AGENTS_MD
    assert "sections/visual-specs.json" in AGENTS_MD
    for field in ("label", "type", "source", "caption"):
        assert field in AGENTS_MD
    assert '"mermaid"' in AGENTS_MD
    assert '"chart"' in AGENTS_MD
    assert "auto-bind" in AGENTS_MD.lower() or "auto-binds" in AGENTS_MD.lower()
    assert "WARN" in AGENTS_MD
