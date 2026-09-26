from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs.domain.workspace_format import (
    CANONICAL_WORKSPACE_SCHEMA,
    WorkspaceFormatError,
    validate_workspace_layout,
    validate_workspace_marker,
    write_workspace_marker,
)


def test_validate_workspace_marker_accepts_only_the_canonical_schema(tmp_path: Path) -> None:
    marker = tmp_path / "workspace.json"
    marker.write_text('{"schema":"docs.workspace/v1"}', encoding="utf-8")

    assert validate_workspace_marker(tmp_path) == CANONICAL_WORKSPACE_SCHEMA


@pytest.mark.parametrize(
    ("content", "error_code"),
    [
        (None, "workspace_marker_missing"),
        ("{", "workspace_marker_malformed"),
        ("[]", "workspace_marker_not_object"),
        ("{}", "workspace_schema_missing"),
        ('{"schema": 1}', "workspace_schema_not_string"),
        ('{"schema":"docs.workspace/v2"}', "workspace_schema_unsupported"),
        ('{"schema":"docs.workspace/v1","extra":true}', "workspace_marker_unknown_fields"),
        ('{"schema":"docs.workspace/v1","schema":"docs.workspace/v1"}', "workspace_marker_duplicate_key"),
    ],
)
def test_validate_workspace_marker_rejects_invalid_or_unknown_formats(
    tmp_path: Path, content: str | None, error_code: str
) -> None:
    if content is not None:
        (tmp_path / "workspace.json").write_text(content, encoding="utf-8")

    with pytest.raises(WorkspaceFormatError) as caught:
        validate_workspace_marker(tmp_path)

    assert caught.value.code == error_code
    assert str(tmp_path / "workspace.json") in str(caught.value)


def test_validate_workspace_layout_requires_both_content_roots_below_workspace(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(WorkspaceFormatError, match="workspace_path_outside_root"):
        validate_workspace_layout(root, root / "documents", tmp_path / "templates")


def test_write_workspace_marker_publishes_the_exact_marker_without_a_temporary_file(
    tmp_path: Path,
) -> None:
    write_workspace_marker(tmp_path)

    assert json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8")) == {
        "schema": CANONICAL_WORKSPACE_SCHEMA
    }
    assert list(tmp_path.glob("workspace.json.tmp*")) == []
