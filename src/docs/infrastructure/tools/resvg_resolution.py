# src/docs/infrastructure/tools/resvg_resolution.py
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

# Mirrors `resolve_mmdc_executable`'s PATH-then-config-fallback shape
# (tasks.md 4.1) -- lives alongside `mmdc_resolution.py`/`java_resolution.py`
# as the shared home for cross-cutting tool-executable resolution, one
# function per tool.


def resolve_resvg_executable(paths: dict[str, Any]) -> str | None:
    resolved = shutil.which("resvg")
    if resolved:
        return resolved
    configured = paths.get("resvg_bin")
    if configured and Path(configured).exists() and Path(configured).is_file():
        return str(configured)
    for candidate in paths.get("resvg_fallbacks", []):
        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_file():
            return str(candidate_path)
    return None
