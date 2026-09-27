from pathlib import Path

import pytest

from docs.domain.workspace_format import write_workspace_marker


@pytest.fixture
def canonical_workspace_root(tmp_path: Path) -> Path:
    """Register the per-test temporary directory as a canonical workspace."""
    write_workspace_marker(tmp_path)
    return tmp_path
