"""Validate wheel members against retired runtime path components."""

from __future__ import annotations

import sys
from pathlib import PurePosixPath
from zipfile import ZipFile

# These are retired runtime paths, not words that may occur in supported
# compatibility adapters or their APIs.
FORBIDDEN_PATH_COMPONENTS = frozenset({"v2_atomic", "flat_pipeline"})


def forbidden_members(members: list[str]) -> list[str]:
    """Return members containing a retired runtime path component."""

    return [
        member
        for member in members
        if FORBIDDEN_PATH_COMPONENTS.intersection(
            component.casefold().rsplit(".", 1)[0]
            for component in PurePosixPath(member).parts
        )
    ]


def validate_wheel(path: str) -> None:
    with ZipFile(path) as archive:
        bad = forbidden_members(archive.namelist())
    if bad:
        raise SystemExit(f"forbidden package entries: {bad}")


if __name__ == "__main__":
    for artifact in sys.argv[1:]:
        if artifact.endswith(".whl"):
            validate_wheel(artifact)
