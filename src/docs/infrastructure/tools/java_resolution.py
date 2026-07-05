# src/docs/infrastructure/tools/java_resolution.py
from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# Moved out of `infrastructure/ingest/opendataloader_pdf_adapter.py` (D5,
# tech-debt closeout — deferred PR6 fresh-review SUGGESTION): the docx-named
# `tool_resolver_adapter.py` was reaching into an ingest adapter for this
# unrelated helper. Lives here, alongside no other tool resolver today, as
# the shared home for cross-cutting tool-executable resolution.


def resolve_java_executable(paths: dict[str, Any]) -> str | None:
    """Mirrors `resolve_pandoc_executable`'s PATH-then-config-fallback shape
    (5.1 spike condition: resolve Java via the existing `ToolResolverPort`
    pattern). `opendataloader_pdf`'s bundled runner always invokes the bare
    `"java"` command, so a configured `java_bin`/`java_fallbacks` entry only
    takes effect when its directory is temporarily prepended to `PATH`
    (see `java_on_path` below) for the duration of the conversion call."""
    resolved = shutil.which("java")
    if resolved:
        return resolved
    configured = paths.get("java_bin")
    if configured and Path(configured).exists() and Path(configured).is_file():
        return str(configured)
    for candidate in paths.get("java_fallbacks", []):
        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_file():
            return str(candidate_path)
    return None


@contextmanager
def java_on_path(java_executable: str) -> Iterator[None]:
    java_dir = str(Path(java_executable).parent)
    original = os.environ.get("PATH", "")
    if java_dir and java_dir not in original.split(os.pathsep):
        os.environ["PATH"] = java_dir + os.pathsep + original
    try:
        yield
    finally:
        os.environ["PATH"] = original
