from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def resolve_pandoc_executable(paths: dict[str, Any]) -> str | None:
    resolved = shutil.which("pandoc")
    if resolved:
        return resolved
    configured = paths.get("pandoc_bin")
    if configured and Path(configured).exists() and Path(configured).is_file():
        return str(configured)
    for candidate in paths.get("pandoc_fallbacks", []):
        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_file():
            return str(candidate_path)
    return None
