# src/docs/application/qa.py
from __future__ import annotations

import inspect
import shutil
from pathlib import Path
from typing import Any

from docs.application.format_audit import FormatAuditService
from docs.application.render_verification import RenderVerificationService
from docs.domain.artifacts import RenderProfile, VerificationReport
from docs.domain.ports.qa_render_port import QaRenderPort
from docs.domain.qa import ensure_child_path, render_qa_report
from docs.domain.review import Issue, ReviewDimension, ReviewResult
from docs.domain.visual_baseline import compare_preview_baseline


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
        output_dir, audit = self.inspect_docx(config, docx_path, strict)
        failures = [issue for issue in audit.issues if issue.severity == "error" and (
            strict or issue.code.startswith("render.")
        )]
        failures.sort(key=lambda issue: not issue.code.startswith("render."))
        if failures:
            raise RuntimeError(f"{failures[0].message}; revisar {output_dir / 'qa-report.md'}")
        return output_dir

    def inspect_docx(
        self, config: dict[str, Any], docx_path: Path, strict: bool = False
    ) -> tuple[Path, ReviewResult]:
        """Return structured rendered QA findings as well as durable evidence.

        qa_docx keeps its Path-returning native API; staged review uses
        these findings directly rather than parsing Markdown or dropping warnings.
        """
        if not docx_path.exists():
            raise FileNotFoundError(f"No existe DOCX para QA: {docx_path}")

        settings = config.get("visual_qa", {})
        if not isinstance(settings, dict) or any(
            not isinstance(settings.get(key, False), bool) for key in ("require_previews", "allow_blank_pages")
        ):
            raise ValueError("Invalid visual QA profile: preview and blank-page options must be booleans")
        preview_stem = settings.get("preview_stem", docx_path.stem)
        baseline_dir, minimum_similarity = self._visual_baseline_config(config, docx_path)
        profile = RenderProfile(
            format="pdf", allow_blank_pages=settings.get("allow_blank_pages", False),
            require_previews=settings.get("require_previews", False),
            expected_page_size=settings.get("expected_page_size"), preview_stem=preview_stem,
            baseline_dir=baseline_dir,
            minimum_similarity=minimum_similarity,
            baseline_strict=strict,
        )
        output_dir = Path(config["paths"]["output_qa_dir"]) / preview_stem
        if baseline_dir is not None and (
            baseline_dir.resolve().is_relative_to(output_dir.resolve())
            or output_dir.resolve().is_relative_to(baseline_dir.resolve())
        ):
            raise ValueError("QA output and baseline directories must not overlap")
        if output_dir.exists():
            ensure_child_path(Path(config["paths"]["output_qa_dir"]), output_dir)
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        # The visual PDF render is the ONLY part of QA that needs LibreOffice;
        # the format audit below (margins, fonts, spacing) is pure python-docx.
        # In draft, a missing optional tool degrades to a reported skip rather
        # than denying the user their document. Strict still raises: asking for
        # strict QA is asking for the full evidence, render included.
        render_error: str | None = None
        try:
            expected_pdf: Path | None = self.port.render_docx_to_pdf(config, docx_path, output_dir)
        except RuntimeError as exc:
            render_error = str(exc)
            expected_pdf = None

        render_verification: VerificationReport | None = None
        if expected_pdf is not None and self.render_verification_service is not None:
            verifier = self.render_verification_service.verify
            if "config" in inspect.signature(verifier).parameters:
                render_verification = verifier(expected_pdf, profile, output_dir / "previews", config)
            else:
                render_verification = verifier(expected_pdf, profile, output_dir / "previews")

        # The PDF verifier renders one deterministic PNG per page when a
        # preview directory is supplied. Reuse those previews as the QA
        # evidence instead of maintaining a second renderer.
        previews_dir = output_dir / "previews"
        pngs = sorted(previews_dir.glob("*.png")) if previews_dir.is_dir() else []

        audit = self.format_audit_service.audit_format(docx_path, config, strict=strict)
        document_audits = self.port.run_documents_audits(config, docx_path, output_dir, strict)
        # Keep the legacy/manual path for callers that intentionally omit the
        # shared verifier.  When it is composed, baseline comparison belongs to
        # RenderVerificationAdapter so every format follows the same contract.
        if baseline_dir is not None and render_verification is None:
            for finding in compare_preview_baseline(
                previews_dir,
                baseline_dir,
                minimum_similarity=minimum_similarity,
                strict=strict,
            ):
                audit.issues.append(
                    Issue(
                        finding.severity,
                        finding.message,
                        code=finding.code,
                        dimension=ReviewDimension.VISUAL,
                        page=finding.page,
                        stage_originator="visual-baseline",
                    )
                )
        if render_error is not None:
            audit.issues.append(Issue(
                "error" if strict else "warning", f"DOCX render unavailable: {render_error}",
                code="render.capability.unavailable", dimension=ReviewDimension.VISUAL,
            ))
        if render_verification is not None:
            for render_finding in render_verification.findings:
                if render_finding.severity != "info":
                    audit.issues.append(Issue(
                        render_finding.severity, f"[{render_finding.code}] {render_finding.message}", code=render_finding.code,
                        dimension=(ReviewDimension.ACCESSIBILITY if render_finding.dimension == "accessibility"
                                   else ReviewDimension.VISUAL), page=render_finding.page,
                    ))
            if not render_verification.passed:
                audit.issues.insert(0, Issue("error", "Verificación de render falló.",
                                            code="render.failed", dimension=ReviewDimension.VISUAL))
        if (strict or settings.get("require_previews", False)) and not pngs:
            audit.issues.append(Issue(
                "error", (f"QA estricto requiere PNG por página y no se generó ninguno en: {output_dir}" if strict
                          else f"QA requires PNG previews per page; none were generated in: {output_dir}"),
                code="render.previews.required", dimension=ReviewDimension.VISUAL,
            ))
        if baseline_dir is not None and not pngs:
            audit.issues.append(Issue(
                "error" if strict else "warning", "Visual baseline cannot be compared without rendered previews.",
                code="visual.baseline_unreadable", dimension=ReviewDimension.VISUAL,
            ))
        if strict:
            for item in document_audits:
                if not item["ok"]:
                    audit.issues.append(Issue("error", f"Auditoría Documents falló: {item['name']}",
                                             dimension=ReviewDimension.VISUAL))
        report = render_qa_report(docx_path, expected_pdf, pngs, audit, document_audits, render_verification)
        (output_dir / "qa-report.md").write_text(report, encoding="utf-8")
        return output_dir, audit

    @staticmethod
    def _visual_baseline_config(
        config: dict[str, Any], docx_path: Path
    ) -> tuple[Path | None, float]:
        """Resolve the opt-in baseline without making it a build requirement."""
        visual_qa = config.get("visual_qa")
        paths = config.get("paths")
        raw_dir: object = visual_qa.get("baseline_dir") if isinstance(visual_qa, dict) else None
        if raw_dir is None and isinstance(paths, dict):
            raw_dir = paths.get("visual_baseline_dir")
        if not isinstance(raw_dir, str) or not raw_dir.strip():
            return None, 0.75
        baseline_dir = Path(raw_dir)
        if not baseline_dir.is_absolute():
            baseline_dir = docx_path.parent / baseline_dir
        minimum = visual_qa.get("minimum_similarity", 0.75) if isinstance(visual_qa, dict) else 0.75
        if not isinstance(minimum, (int, float)) or isinstance(minimum, bool):
            raise ValueError("visual_qa.minimum_similarity must be a number")
        return baseline_dir, float(minimum)
