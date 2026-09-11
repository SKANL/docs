# src/docs/application/qa.py
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from docs.application.format_audit import FormatAuditService
from docs.application.render_verification import RenderVerificationService
from docs.domain.artifacts import RenderProfile, VerificationReport
from docs.domain.ports.qa_render_port import QaRenderPort
from docs.domain.qa import ensure_child_path, render_qa_report
from docs.domain.review import Issue


class QaService:
    def __init__(
        self,
        port: QaRenderPort,
        format_audit_service: FormatAuditService,
        render_verification_service: RenderVerificationService | None = None,
    ) -> None:
        self.port = port
        self.format_audit_service = format_audit_service
        self.render_verification_service = render_verification_service

    def qa_docx(self, config: dict[str, Any], docx_path: Path, strict: bool = False) -> Path:
        if not docx_path.exists():
            raise FileNotFoundError(f"No existe DOCX para QA: {docx_path}")

        output_dir = Path(config["paths"]["output_qa_dir"]) / docx_path.stem
        if output_dir.exists():
            ensure_child_path(Path(config["paths"]["output_qa_dir"]), output_dir)
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        # The visual PDF render is the ONLY part of QA that needs LibreOffice;
        # the format audit below (margins, fonts, spacing) is pure python-docx.
        # In draft, a missing optional tool degrades to a reported skip rather
        # than denying the user their document. Strict still raises: asking for
        # strict QA is asking for the full evidence, render included.
        try:
            expected_pdf: Path | None = self.port.render_docx_to_pdf(config, docx_path, output_dir)
        except RuntimeError:
            if strict:
                raise
            expected_pdf = None

        render_verification: VerificationReport | None = None
        if expected_pdf is not None and self.render_verification_service is not None:
            render_verification = self.render_verification_service.verify(
                expected_pdf, RenderProfile(format="pdf"), output_dir / "previews"
            )

        # PNG-per-page rendering is permanently out of scope (user decision,
        # 2026-06-21) — will be reimplemented differently later. Verbatim
        # strict-mode consequence preserved: strict QA still requires PNG
        # evidence and therefore always raises here until that capability
        # lands under a future, differently-shaped slice.
        pngs: list[Path] = []

        audit = self.format_audit_service.audit_format(docx_path, config, strict=strict)
        document_audits = self.port.run_documents_audits(config, docx_path, output_dir, strict)
        strict_failures: list[str] = []
        if strict and render_verification is not None and not render_verification.passed:
            message = "Verificación de render falló."
            audit.issues.append(Issue("error", message))
            strict_failures.append(message)
        if strict and not pngs:
            message = f"QA estricto requiere PNG por página y no se generó ninguno en: {output_dir}"
            audit.issues.append(Issue("error", message))
            strict_failures.append(message)
        if strict:
            for item in document_audits:
                if not item["ok"]:
                    audit.issues.append(Issue("error", f"Auditoría Documents falló: {item['name']}"))
        report = render_qa_report(docx_path, expected_pdf, pngs, audit, document_audits, render_verification)
        (output_dir / "qa-report.md").write_text(report, encoding="utf-8")
        if strict and strict_failures:
            raise RuntimeError(f"{strict_failures[0]}; revisar {output_dir / 'qa-report.md'}")
        if strict and not audit.passed:
            raise RuntimeError(f"QA estricto falló; revisar {output_dir / 'qa-report.md'}")
        return output_dir
