from pathlib import Path

import pytest

from docs.domain.workspace_format import write_workspace_marker


@pytest.fixture
def canonical_workspace_root(tmp_path: Path) -> Path:
    """Register the per-test temporary directory as a canonical workspace."""
    write_workspace_marker(tmp_path)
    return tmp_path


@pytest.fixture
def canonical_cli_workspace(
    canonical_workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Configure an isolated CLI workspace rooted at a canonical marker."""
    documents = canonical_workspace_root / "documents"
    templates = canonical_workspace_root / "templates"
    documents.mkdir()
    templates.mkdir()
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(documents))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    return canonical_workspace_root
