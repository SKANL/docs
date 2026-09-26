"""Canonical workspace marker and containment validation."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

CANONICAL_WORKSPACE_SCHEMA = "docs.workspace/v1"
WORKSPACE_MARKER_FILENAME = "workspace.json"


class WorkspaceFormatError(ValueError):
    """A canonical workspace contract violation with an actionable code."""

    def __init__(self, code: str, path: Path) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code}: {path}")


class _DuplicateKeyError(ValueError):
    pass


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKeyError(key)
        value[key] = item
    return value


def validate_workspace_marker(root: str | Path) -> str:
    """Validate the exact v1 marker without mutating the workspace."""
    marker = Path(root).expanduser().resolve() / WORKSPACE_MARKER_FILENAME
    if not marker.is_file():
        raise WorkspaceFormatError("workspace_marker_missing", marker)
    try:
        value = json.loads(
            marker.read_text(encoding="utf-8"),
            object_pairs_hook=_closed_object,
        )
    except _DuplicateKeyError as exc:
        raise WorkspaceFormatError("workspace_marker_duplicate_key", marker) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkspaceFormatError("workspace_marker_malformed", marker) from exc
    if not isinstance(value, dict):
        raise WorkspaceFormatError("workspace_marker_not_object", marker)
    unknown_fields = set(value) - {"schema"}
    if unknown_fields:
        raise WorkspaceFormatError("workspace_marker_unknown_fields", marker)
    if "schema" not in value:
        raise WorkspaceFormatError("workspace_schema_missing", marker)
    if not isinstance(value["schema"], str):
        raise WorkspaceFormatError("workspace_schema_not_string", marker)
    if value["schema"] != CANONICAL_WORKSPACE_SCHEMA:
        raise WorkspaceFormatError("workspace_schema_unsupported", marker)
    return CANONICAL_WORKSPACE_SCHEMA


def validate_workspace_layout(
    root: str | Path,
    documents_dir: str | Path,
    templates_dir: str | Path,
) -> None:
    """Require both content roots to resolve strictly below one root."""
    resolved_root = Path(root).expanduser().resolve()
    for candidate in (documents_dir, templates_dir):
        resolved = Path(candidate).expanduser().resolve()
        if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
            raise WorkspaceFormatError("workspace_path_outside_root", resolved)


def write_workspace_marker(root: str | Path) -> Path:
    """Atomically publish the exact canonical marker, preserving valid markers."""
    resolved_root = Path(root).expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    marker = resolved_root / WORKSPACE_MARKER_FILENAME
    if marker.exists():
        validate_workspace_marker(resolved_root)
        return marker

    temporary = marker.with_name(f"{marker.name}.tmp-{uuid4().hex}")
    try:
        temporary.write_text(
            f'{{"schema":"{CANONICAL_WORKSPACE_SCHEMA}"}}\n',
            encoding="utf-8",
        )
        temporary.replace(marker)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return marker
