from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from docs.application.format_audit import FormatAuditService
from docs.application.qa import QaService
from docs.application.render_verification import RenderVerificationService
from docs.application.review import ReviewService
from docs.application.structural_audit import StructuralAuditService
from docs.domain.artifacts import RenderProfile
from docs.domain.models.template import Template
from docs.domain.normative import resolve_normative_settings
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.review import Issue, ReviewDimension, ReviewResult


@dataclass(frozen=True)
class ReviewStageOutcome:
    ok: bool
    detail: str
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class ReviewStageService:
    """Run the document QA dimensions through the existing application services."""

    def __init__(
        self,
        *,
        structural_audit: StructuralAuditService,
        format_audit: FormatAuditService,
        document_review: ReviewService,
        rules_manifest_state: Callable[[dict[str, Any]], tuple[bool, int]],
        render_verification: RenderVerificationService | None = None,
        qa: QaService | None = None,
        pdf_reproducibility: Callable[[Path, Path], tuple[bool, str]] | None = None,
    ) -> None:
        self._structural_audit = structural_audit
        self._format_audit = format_audit
        self._document_review = document_review
        self._rules_manifest_state = rules_manifest_state
        self._render_verification = render_verification
        self._qa = qa
        self._pdf_reproducibility = pdf_reproducibility

    def run_all(
        self,
        *,
        document_id: str,
        artifact_path: Path,
        config: dict[str, Any],
        template: Template,
        policy: PipelinePolicy,
        rebuild: Callable[[Path], str | Path | None],
        scratch_dir: Path,
    ) -> dict[str, ReviewStageOutcome]:
        return {
            stage: self.run_stage(
                stage,
                document_id=document_id,
                artifact_path=artifact_path,
                config=config,
                template=template,
                policy=policy,
                rebuild=rebuild,
                scratch_dir=scratch_dir,
            )
            for stage in (
                "structural-audit",
                "editorial-review",
                "evidence-review",
                "consistency-review",
                "accessibility-review",
                "visual-review",
                "reproducibility-check",
            )
        }

    def run_stage(
        self,
        stage: str,
        *,
        document_id: str,
        artifact_path: Path,
        config: dict[str, Any],
        template: Template,
        policy: PipelinePolicy,
        rebuild: Callable[[Path], str | Path | None],
        scratch_dir: Path,
    ) -> ReviewStageOutcome:
        if stage == "structural-audit":
            return self.structural_audit(artifact_path, template, policy)
        if stage == "editorial-review":
            return self.editorial_review(document_id, template, config, policy)
        if stage == "evidence-review":
            return self.evidence_review(document_id, template, config, policy)
        if stage == "consistency-review":
            return self.consistency_review(document_id, template, config, policy)
        if stage == "accessibility-review":
            return self.accessibility_review(artifact_path, config, policy)
        if stage == "visual-review":
            return self.visual_review(artifact_path, config, policy)
        if stage == "reproducibility-check":
            return self.reproducibility_check(artifact_path, policy, rebuild, scratch_dir)
        raise ValueError(f"unsupported review stage: {stage}")

    def structural_audit(
        self, artifact_path: Path, template: Template, policy: PipelinePolicy
    ) -> ReviewStageOutcome:
        contract = template.template_contract
        rules = {} if contract is None else contract.model_dump(exclude_none=True)
        return self._outcome(self._structural_audit.audit(artifact_path, rules), policy)

    def editorial_review(
        self,
        document_id: str,
        template: Template,
        config: dict[str, Any],
        policy: PipelinePolicy,
    ) -> ReviewStageOutcome:
        manifest_exists, manifest_size = self._rules_manifest_state(config)
        result = self._document_review.review_document(
            document_id,
            template,
            strict=policy.mode in {PipelineMode.strict, PipelineMode.release},
            manifest_exists=manifest_exists,
            manifest_size=manifest_size,
            normative=resolve_normative_settings(config),
        )
        return self._outcome(result.filter_dimensions({ReviewDimension.EDITORIAL}), policy)

    def accessibility_review(
        self, artifact_path: Path, config: dict[str, Any], policy: PipelinePolicy
    ) -> ReviewStageOutcome:
        if artifact_path.suffix.lower() in {".html", ".htm", ".pdf"}:
            return self._render_review(artifact_path, config, policy, ReviewDimension.ACCESSIBILITY)
        result = self._format_audit.audit_format(
            artifact_path,
            config,
            strict=policy.mode in {PipelineMode.strict, PipelineMode.release},
        )
        return self._outcome(result.filter_dimensions({ReviewDimension.ACCESSIBILITY}), policy)

    def evidence_review(
        self,
        document_id: str,
        template: Template,
        config: dict[str, Any],
        policy: PipelinePolicy,
    ) -> ReviewStageOutcome:
        return self._document_dimension_review(
            document_id, template, config, policy, ReviewDimension.EVIDENCE
        )

    def consistency_review(
        self,
        document_id: str,
        template: Template,
        config: dict[str, Any],
        policy: PipelinePolicy,
    ) -> ReviewStageOutcome:
        return self._document_dimension_review(
            document_id, template, config, policy, ReviewDimension.CONSISTENCY
        )

    def _document_dimension_review(
        self,
        document_id: str,
        template: Template,
        config: dict[str, Any],
        policy: PipelinePolicy,
        dimension: ReviewDimension,
    ) -> ReviewStageOutcome:
        manifest_exists, manifest_size = self._rules_manifest_state(config)
        result = self._document_review.review_document(
            document_id,
            template,
            strict=policy.mode in {PipelineMode.strict, PipelineMode.release},
            manifest_exists=manifest_exists,
            manifest_size=manifest_size,
            normative=resolve_normative_settings(config),
        )
        return self._outcome(result.filter_dimensions({dimension}), policy)

    def visual_review(
        self, artifact_path: Path, config: dict[str, Any], policy: PipelinePolicy
    ) -> ReviewStageOutcome:
        if artifact_path.suffix.lower() in {".html", ".htm", ".pdf"}:
            return self._render_review(artifact_path, config, policy, ReviewDimension.VISUAL)
        strict = policy.mode in {PipelineMode.strict, PipelineMode.release}
        if self._qa is not None:
            try:
                _, result = self._qa.inspect_docx(config, artifact_path, strict=strict)
            except (OSError, RuntimeError, ValueError, KeyError) as exc:
                result = ReviewResult([Issue("error", f"DOCX QA failed: {exc}",
                                             code="render.open", dimension=ReviewDimension.VISUAL)])
        else:
            result = self._format_audit.audit_format(artifact_path, config, strict=strict)
            settings = config.get("visual_qa", {})
            if settings or config.get("paths", {}).get("visual_baseline_dir"):
                required = isinstance(settings, dict) and settings.get("require_previews", False)
                result.issues.append(Issue(
                    "error" if required else "warning",
                    "DOCX rendered QA is not configured; baseline/previews are unverified.",
                    code="render.previews.required" if required else "render.capability.unavailable",
                    dimension=ReviewDimension.VISUAL,
                ))
        return self._outcome(result.filter_dimensions({ReviewDimension.VISUAL}), policy)

    def _render_review(
        self, path: Path, config: dict[str, Any], policy: PipelinePolicy, dimension: ReviewDimension
    ) -> ReviewStageOutcome:
        if not path.is_file():
            return self._outcome(ReviewResult([Issue(
                "error", f"Artifact is missing: {path}", code="render.open", dimension=dimension,
            )]), policy)
        if self._render_verification is None:
            return self._outcome(ReviewResult([Issue(
                "warning", "Multiformat render verification port is not configured; QA is unverified.",
                code="render.capability.unavailable", dimension=dimension,
            )]), policy)
        visual = dimension is ReviewDimension.VISUAL
        settings = config.get("visual_qa", {}) if visual else {}
        if not isinstance(settings, dict) or any(
            not isinstance(settings.get(key, False), bool) for key in ("allow_blank_pages", "require_previews")
        ):
            return self._outcome(ReviewResult([Issue(
                "error", "Invalid visual QA profile: preview and blank-page options must be booleans.",
                code="render.profile.invalid", dimension=dimension,
            )]), policy)
        expected = settings.get("expected_page_size")
        if expected is not None and (not isinstance(expected, (list, tuple)) or len(expected) != 2 or any(
            type(value) not in {int, float} or not math.isfinite(value) or value <= 0 for value in expected
        )):
            return self._outcome(ReviewResult([Issue(
                "error", "Invalid visual QA profile: expected_page_size needs two positive finite dimensions.",
                code="render.profile.invalid", dimension=dimension,
            )]), policy)
        baseline_dir = settings.get("baseline_dir")
        minimum_similarity = settings.get("minimum_similarity", 0.75)
        browser_viewports = settings.get("browser_viewports", ((1280, 800), (390, 844)))
        if not isinstance(browser_viewports, (list, tuple)) or not browser_viewports or any(
            not isinstance(viewport, (list, tuple)) or len(viewport) != 2
            or any(type(value) is not int or value <= 0 for value in viewport)
            for viewport in browser_viewports
        ):
            return self._outcome(ReviewResult([Issue(
                "error", "Invalid visual QA profile: browser_viewports needs positive width/height pairs.",
                code="render.profile.invalid", dimension=dimension,
            )]), policy)
        if baseline_dir is not None and (not isinstance(baseline_dir, str) or not baseline_dir.strip()):
            return self._outcome(ReviewResult([Issue(
                "error", "Invalid visual QA profile: baseline_dir must be a nonempty path string.",
                code="render.profile.invalid", dimension=dimension,
            )]), policy)
        if type(minimum_similarity) not in {int, float} or not math.isfinite(minimum_similarity) or not 0 <= minimum_similarity <= 1:
            return self._outcome(ReviewResult([Issue(
                "error", "Invalid visual QA profile: minimum_similarity must be between 0 and 1.",
                code="render.profile.invalid", dimension=dimension,
            )]), policy)
        preview_root = config.get("paths", {}).get("output_qa_dir") if visual else None
        previews = Path(preview_root) / settings.get("preview_stem", path.stem) / "previews" if preview_root else None
        profile = RenderProfile(
            format="html" if path.suffix.lower() in {".html", ".htm"} else "pdf",
            expected_page_size=tuple(expected) if expected is not None else None,
            allow_blank_pages=settings.get("allow_blank_pages", False),
            require_previews=settings.get("require_previews", False),
            baseline_dir=(path.parent / baseline_dir if baseline_dir is not None and not Path(baseline_dir).is_absolute()
                          else Path(baseline_dir) if baseline_dir is not None else None),
            minimum_similarity=float(minimum_similarity),
            baseline_strict=policy.mode in {PipelineMode.strict, PipelineMode.release},
            preview_stem=settings.get("preview_stem"),
            browser_viewports=tuple(tuple(viewport) for viewport in browser_viewports),
        )
        try:
            report = self._render_verification.verify(path, profile, previews, config)
        except (OSError, RuntimeError, ValueError) as exc:
            return self._outcome(ReviewResult([Issue(
                "error", f"Artifact QA failed: {exc}", code="render.open", dimension=dimension,
            )]), policy)
        technical = {"render.open", "render.format_mismatch", "render.pages.empty", "render.dimensions", "artifact.identity_changed"}
        issues = [Issue(
            finding.severity, f"[{finding.code}] {finding.message}", code=finding.code,
            dimension=dimension, page=finding.page, file=finding.path,
            stage_originator=f"{dimension.value}-review",
        ) for finding in report.findings if finding.severity != "info" and (
            (visual and finding.dimension != "accessibility")
            or (not visual and (finding.dimension == "accessibility" or finding.code in technical))
        )]
        return self._outcome(ReviewResult(issues), policy)

    def reproducibility_check(
        self,
        artifact_path: Path,
        policy: PipelinePolicy,
        rebuild: Callable[[Path], str | Path | None],
        scratch_dir: Path,
    ) -> ReviewStageOutcome:
        rebuilt = scratch_dir / artifact_path.name
        try:
            scratch_dir.mkdir(parents=True, exist_ok=True)
            candidate = rebuild(rebuilt)
            if candidate is None:
                raise RuntimeError("reproducibility check produced no artifact")
            rebuilt = Path(candidate)
            if artifact_path.suffix.lower() == ".pdf":
                if self._pdf_reproducibility is None:
                    raise RuntimeError("PDF semantic reproducibility comparator is not configured")
                passed, detail = self._pdf_reproducibility(artifact_path, rebuilt)
                if not passed:
                    raise RuntimeError(detail)
            elif sha256(artifact_path.read_bytes()).digest() != sha256(rebuilt.read_bytes()).digest():
                raise RuntimeError("reproducibility divergence detected")
        except Exception as exc:
            return self._outcome(
                ReviewResult(
                    [
                        Issue(
                            "error",
                            f"reproducibility check failed: {exc}",
                            code="reproducibility.failed",
                            dimension=ReviewDimension.REPRODUCIBILITY,
                        )
                    ]
                ),
                policy,
            )
        return self._outcome(ReviewResult([]), policy)

    @staticmethod
    def _outcome(result: ReviewResult, policy: PipelinePolicy) -> ReviewStageOutcome:
        result = ReviewResult([replace(issue, severity=policy.severity(issue.code, issue.severity)) for issue in result.issues])
        warnings: list[str] = []
        errors: list[str] = []
        for issue in result.issues:
            severity = policy.severity(issue.code, issue.severity)
            if severity == "error":
                errors.append(issue.message)
            elif severity == "warning":
                warnings.append(issue.message)
        detail = result.to_markdown()
        return ReviewStageOutcome(not errors, detail, tuple(warnings), tuple(errors))
