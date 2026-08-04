# src/docs/infrastructure/tools/mmdc_resolution.py
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

# Mirrors `resolve_pandoc_executable`'s PATH-then-config-fallback shape
# (tasks.md 3.1) -- lives alongside `java_resolution.py` as the shared home
# for cross-cutting tool-executable resolution, one function per tool.


def resolve_mmdc_executable(paths: dict[str, Any]) -> str | None:
    resolved = shutil.which("mmdc")
    if resolved:
        return resolved
    configured = paths.get("mmdc_bin")
    if configured and Path(configured).exists() and Path(configured).is_file():
        return str(configured)
    for candidate in paths.get("mmdc_fallbacks", []):
        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_file():
            return str(candidate_path)
    return None
