# src/docs/infrastructure/tools/mmdc_resolution.py
from __future__ import annotations

from typing import Any

from docs.infrastructure.tools.resolution import resolve_executable

# Mirrors `resolve_pandoc_executable`'s PATH-then-config-fallback shape
# (tasks.md 3.1) -- lives alongside `java_resolution.py` as the shared home
# for cross-cutting tool-executable resolution, one function per tool.


def resolve_mmdc_executable(paths: dict[str, Any]) -> str | None:
    return resolve_executable(
        paths, names=("mmdc",), config_prefix="mmdc"
    )