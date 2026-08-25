# src/docs/infrastructure/tools/java_resolution.py
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from docs.infrastructure.tools.resolution import resolve_executable

# Moved out of `infrastructure/ingest/opendataloader_pdf_adapter.py` (D5,
# tech-debt closeout — deferred PR6 fresh-review SUGGESTION): the docx-named
# `tool_resolver_adapter.py` was reaching into an ingest adapter for this
# unrelated helper. Lives here, alongside no other tool resolver today, as
# the shared home for cross-cutting tool-executable resolution.


def resolve_java_executable(paths: dict[str, Any]) -> str | None:
    """Mirrors every other toolchain resolver (5.1 spike condition: resolve
    Java via the existing `ToolResolverPort` pattern). `opendataloader_pdf`
    always invokes the bare `"java"` command, so a configured
    `java_bin`/`java_fallbacks` entry only takes effect while its directory
    is prepended to `PATH` (see `java_on_path` below)."""
    return resolve_executable(
        paths, names=("java",), config_prefix="java"
    )


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
