from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from docs.application.format_audit import FormatAuditService
from docs.application.review import ReviewService
from docs.application.structural_audit import StructuralAuditService
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
    ) -> None:
        self._structural_audit = structural_audit
        self._format_audit = format_audit
        self._document_review = document_review
        self._rules_manifest_state = rules_manifest_state

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
        result = self._format_audit.audit_format(
            artifact_path,
            config,
            strict=policy.mode in {PipelineMode.strict, PipelineMode.release},
        )
        return self._outcome(result.filter_dimensions({ReviewDimension.VISUAL}), policy)

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
            if sha256(artifact_path.read_bytes()).digest() != sha256(rebuilt.read_bytes()).digest():
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
        warnings: list[str] = []
        errors: list[str] = []
        for issue in result.issues:
            severity = policy.severity(issue.code, issue.severity)
            if severity == "error":
                errors.append(issue.message)
            else:
                warnings.append(issue.message)
        detail = result.to_markdown()
        return ReviewStageOutcome(not errors, detail, tuple(warnings), tuple(errors))
