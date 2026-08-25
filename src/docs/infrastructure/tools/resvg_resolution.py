# src/docs/infrastructure/tools/resvg_resolution.py
from __future__ import annotations

from typing import Any

from docs.infrastructure.tools.resolution import resolve_executable

# Mirrors `resolve_mmdc_executable`'s PATH-then-config-fallback shape
# (tasks.md 4.1) -- lives alongside `mmdc_resolution.py`/`java_resolution.py`
# as the shared home for cross-cutting tool-executable resolution, one
# function per tool.


def resolve_resvg_executable(paths: dict[str, Any]) -> str | None:
    return resolve_executable(
        paths, names=("resvg",), config_prefix="resvg"
    )