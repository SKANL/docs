from __future__ import annotations

from typing import Any, Protocol


class ToolResolverPort(Protocol):
    def resolve_pandoc(self, paths: dict[str, Any]) -> str | None: ...
    def resolve_libreoffice(self, paths: dict[str, Any]) -> str | None: ...
    def resolve_java(self, paths: dict[str, Any]) -> str | None: ...
    def resolve_mmdc(self, paths: dict[str, Any]) -> str | None: ...
    def resolve_resvg(self, paths: dict[str, Any]) -> str | None: ...

    def tool_version(self, executable: str) -> str | None:
        """Raw `--version` output for an already-resolved executable.

        One method rather than one per tool: every external toolchain here
        answers the same question the same way, and five near-identical
        methods would be five places to keep in step. Parsing what comes back
        is `domain/tool_versions.py`'s job; this only performs the I/O.
        """
        ...
