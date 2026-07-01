from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class QaRenderPort(Protocol):
    def render_docx_to_pdf(self, config: dict[str, Any], docx_path: Path, output_dir: Path) -> Path: ...
    def run_documents_audits(
        self, config: dict[str, Any], docx_path: Path, output_dir: Path, strict: bool
    ) -> list[dict[str, Any]]: ...
