# src/docs/application/format_audit.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.ports.docx_audit_port import DocxAuditPort
from docs.domain.review import ReviewResult


class FormatAuditService:
    def __init__(self, port: DocxAuditPort) -> None:
        self.port = port

    def audit_format(self, docx_path: Path, config: dict[str, Any], strict: bool = False) -> ReviewResult:
        if not docx_path.exists():
            raise FileNotFoundError(f"No existe DOCX para auditar: {docx_path}")
        return ReviewResult(self.port.audit(docx_path, config, strict))
