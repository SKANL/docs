# src/docs/infrastructure/tools/java_resolution.py
from __future__ import annotations

import os
import subprocess
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


class _EnvSubprocess:
    """`subprocess` stand-in that hands every child the given environment."""

    def __init__(self, env: dict[str, str]) -> None:
        self._env = env

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return subprocess.run(*args, **{"env": self._env, **kwargs})  # noqa: PLW1510 - check is forwarded by the caller

    def Popen(self, *args: Any, **kwargs: Any) -> Any:
        return subprocess.Popen(*args, **{"env": self._env, **kwargs})

    def __getattr__(self, name: str) -> Any:
        return getattr(subprocess, name)


@contextmanager
def java_on_path(java_executable: str) -> Iterator[None]:
    """Make `opendataloader_pdf`'s bare `java` resolve to `java_executable`.

    The process environment is never mutated: the library's `subprocess`
    reference is swapped for one that passes an augmented `PATH` env to each
    child, then restored.
    """
    # ponytail: the library exposes no env hook, so its module-level `subprocess`
    # is swapped for the duration; not thread-safe across concurrent callers.
    # Upgrade path: an upstream `env=` parameter on run_jar.
    from opendataloader_pdf import runner

    env = dict(os.environ)
    java_dir = str(Path(java_executable).parent)
    path = env.get("PATH", "")
    if java_dir and java_dir not in path.split(os.pathsep):
        env["PATH"] = java_dir + os.pathsep + path
    original = runner.subprocess
    runner.subprocess = _EnvSubprocess(env)  # type: ignore[assignment]
    try:
        yield
    finally:
        runner.subprocess = original
