# src/docs/infrastructure/docx/tool_resolver_adapter.py
from __future__ import annotations

from typing import Any

from docs.infrastructure.docx.libreoffice_qa_adapter import resolve_libreoffice_executable
from docs.infrastructure.docx.python_docx_assembly_adapter import resolve_pandoc_executable
from docs.infrastructure.tools.java_resolution import resolve_java_executable


class SystemToolResolverAdapter:
    """Wraps the already-correct free functions that resolve build/QA/ingest
    tool executables from PATH or config fallbacks, so DoctorService,
    DocxRendererAdapter (formerly DocxAssemblyService, renamed PR4), and
    OpendataloaderPdfAdapter (PR6) depend on ToolResolverPort instead of
    importing infrastructure directly (Slice 16 tech-debt remediation,
    finding 1). Java resolution itself lives in `infrastructure/tools/
    java_resolution.py` (D5, tech-debt closeout) rather than in the
    ingest-specific `opendataloader_pdf_adapter.py`, since this docx-named
    module has no business reaching into an ingest adapter for it."""

    def resolve_pandoc(self, paths: dict[str, Any]) -> str | None:
        return resolve_pandoc_executable(paths)

    def resolve_libreoffice(self, paths: dict[str, Any]) -> str | None:
        return resolve_libreoffice_executable(paths)

    def resolve_java(self, paths: dict[str, Any]) -> str | None:
        return resolve_java_executable(paths)
