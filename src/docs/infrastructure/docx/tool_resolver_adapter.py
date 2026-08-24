# src/docs/infrastructure/docx/tool_resolver_adapter.py
from __future__ import annotations

import subprocess
from typing import Any

from docs.infrastructure.docx.libreoffice_qa_adapter import resolve_libreoffice_executable
from docs.infrastructure.docx.python_docx_assembly_adapter import resolve_pandoc_executable
from docs.infrastructure.tools.java_resolution import resolve_java_executable
from docs.infrastructure.tools.mmdc_resolution import resolve_mmdc_executable
from docs.infrastructure.tools.resvg_resolution import resolve_resvg_executable


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

    def resolve_mmdc(self, paths: dict[str, Any]) -> str | None:
        return resolve_mmdc_executable(paths)

    def resolve_resvg(self, paths: dict[str, Any]) -> str | None:
        return resolve_resvg_executable(paths)

    def tool_version(self, executable: str) -> str | None:
        """Ask a resolved executable for its version, or give up quietly.

        Every failure mode here means "unknown", never "too old": a tool that
        does not answer `--version` the expected way may be perfectly fine,
        and reporting it as outdated would send someone to reinstall
        something that works. Java writes its version to stderr, so both
        streams are read.
        """
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return (result.stdout or "") + (result.stderr or "") or None
