# src/docs/infrastructure/docx/tool_resolver_adapter.py
from __future__ import annotations

from typing import Any

from docs.infrastructure.docx.libreoffice_qa_adapter import resolve_libreoffice_executable
from docs.infrastructure.docx.python_docx_assembly_adapter import resolve_pandoc_executable


class SystemToolResolverAdapter:
    """Wraps the two already-correct free functions that resolve build/QA
    tool executables from PATH or config fallbacks, so DoctorService and
    DocxAssemblyService depend on ToolResolverPort instead of importing
    infrastructure directly (Slice 16 tech-debt remediation, finding 1)."""

    def resolve_pandoc(self, paths: dict[str, Any]) -> str | None:
        return resolve_pandoc_executable(paths)

    def resolve_libreoffice(self, paths: dict[str, Any]) -> str | None:
        return resolve_libreoffice_executable(paths)
