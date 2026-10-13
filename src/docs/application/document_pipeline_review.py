"""Audit and review stages of the document pipeline."""

from __future__ import annotations

import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from docs.application.document_pipeline_context import PipelineContext, stage_success
from docs.application.document_pipeline_verifiers import (
    _fallback_structural_audit,
    _successful_stage_result,
    _verify_non_docx_artifact,
    _verify_pdf_reproducibility,
)
from docs.application.review_stages import ReviewStageService
from docs.domain.identity import sha256_file
from docs.domain.normative import resolve_normative_settings
from docs.domain.pipeline_kernel import StageResult
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.review import ReviewDimension, ReviewResult


def create_review_stage_service(deps: Any) -> ReviewStageService | None:
    """Build the review service only when every collaborator is wired."""
    required = (
        getattr(deps, "structural_audit_service", None),
        getattr(deps, "format_audit", None),
        getattr(deps, "review", None),
        getattr(deps, "render_verification", None),
    )
    if any(service is None for service in required):
        return None
    return ReviewStageService(
        structural_audit=deps.structural_audit_service,
        format_audit=deps.format_audit,
        document_review=deps.review,
        rules_manifest_state=getattr(deps, "rules_manifest_state", lambda _config: (False, 0)),
        render_verification=deps.render_verification,
        qa=getattr(deps, "qa", None) if hasattr(getattr(deps, "qa", None), "inspect_docx") else None,
        pdf_reproducibility=_verify_pdf_reproducibility,
    )


def _messages(issues: Any) -> str:
    return "; ".join(issue.message for issue in issues)


class ReviewStages:
    """Native structural, accessibility, visual and reproducibility reviews."""

    def __init__(
        self,
        ctx: PipelineContext,
        stage_provider: Any,
        review_stage_service: ReviewStageService | None,
    ) -> None:
        self._ctx = ctx
        self._stage_provider = stage_provider
        self.service = review_stage_service

    def structural_audit(self) -> tuple[bool, str]:
        ctx = self._ctx
        service = self._stage_provider.get("structural_audit_service")
        if service is None or not hasattr(service, "audit"):
            return _fallback_structural_audit(ctx.state["artifact"], ctx.output_format)
        template = ctx.state["resolved"].template
        contract = getattr(template, "template_contract", None)
        # Current templates predate the declarative contract.  They still need
        # the generic structural checks (readability, tables, relationships),
        # so an absent contract means "no additional requirements", not "skip
        # the audit".  This keeps migration finite while preserving the v2
        # gate for every rendered artifact.
        contract_data = {} if contract is None else contract.model_dump(exclude_none=True)
        result = service.audit(ctx.state["artifact"], contract_data)
        return result.passed, result.to_markdown()

    def accessibility_review(self) -> tuple[bool, str] | StageResult:
        """Run the existing format audit's accessibility checks as a V2 stage."""
        ctx = self._ctx
        if ctx.output_format != "docx":
            passed, detail = _verify_non_docx_artifact(ctx.output_format, ctx.state["artifact"])
            return passed, f"accessibility reopen: {detail}"
        result: ReviewResult = ctx.deps.format_audit.audit_format(
            ctx.state["artifact"], ctx.state["config"], strict=ctx.strict
        )
        findings = result.filter_dimensions({ReviewDimension.ACCESSIBILITY}).issues
        if not findings:
            return _successful_stage_result("accessibility-review", ctx.state["artifact"])
        return False, _messages(findings)

    def document_review(self, name: str, dimension: ReviewDimension) -> tuple[bool, str]:
        """Reuse the document review service for one native review dimension."""
        ctx = self._ctx
        review_service = getattr(ctx.deps, "review", None)
        manifest_state = self._stage_provider.get("rules_manifest_state")
        if review_service is None or not callable(manifest_state):
            return False, f"{name} service is not configured"
        manifest_exists, manifest_size = manifest_state(ctx.state["config"])
        result = review_service.review_document(
            ctx.state["resolved"].doc_id,
            ctx.state["resolved"].template,
            strict=ctx.strict,
            manifest_exists=manifest_exists,
            manifest_size=manifest_size,
            normative=resolve_normative_settings(ctx.state["config"]),
        )
        findings = result.filter_dimensions({dimension}).issues
        if not findings:
            return stage_success(name)
        return False, _messages(findings)

    def visual_review(self) -> tuple[bool, str]:
        """Reuse the format audit's visual findings for the rendered artifact."""
        ctx = self._ctx
        if ctx.output_format != "docx":
            passed, detail = _verify_non_docx_artifact(ctx.output_format, ctx.state["artifact"])
            return passed, f"visual reopen: {detail}"
        result: ReviewResult = ctx.deps.format_audit.audit_format(
            ctx.state["artifact"], ctx.state["config"]
        )
        findings = result.filter_dimensions({ReviewDimension.VISUAL}).issues
        if not findings:
            return stage_success("visual-review")
        return False, _messages(findings)

    def reproducibility_check(self) -> tuple[bool, str] | StageResult:
        """Rebuild once and compare with the artifact under review."""
        ctx = self._ctx
        artifact = ctx.state.get("artifact")
        renderer = ctx.state.get("renderer")
        if not isinstance(artifact, Path) or renderer is None:
            return False, "reproducibility check has no rendered artifact"
        scratch_dir = Path(tempfile.mkdtemp(prefix=".docs-repro-", dir=ctx.document_root))
        ctx.scratch_dirs.append(scratch_dir)
        try:
            rebuilt = renderer.build(
                ctx.state["resolved"].doc_id,
                ctx.state["config"],
                output=scratch_dir / artifact.name,
            )
            if rebuilt is None:
                return False, "reproducibility check produced no artifact"
            rebuilt_path = Path(rebuilt)
            if ctx.output_format == "pdf":
                passed, detail = _verify_pdf_reproducibility(artifact, rebuilt_path)
                if not passed:
                    return False, detail
            elif sha256_file(artifact) != sha256_file(rebuilt_path):
                return False, "reproducibility divergence detected"
        except Exception as exc:
            return False, f"reproducibility check failed: {exc}"
        return _successful_stage_result("reproducibility-check", artifact)

    def review_stage(self, name: str) -> tuple[bool, str] | StageResult:
        ctx = self._ctx
        if self.service is None:
            return False, f"{name} service is not configured"
        state = ctx.state
        review_config = deepcopy(state["config"])
        visual_settings = review_config.setdefault("visual_qa", {})
        if isinstance(visual_settings, dict):
            visual_settings["preview_stem"] = f"{state['resolved'].doc_id}.{ctx.output_format}"
        outcome = self.service.run_stage(
            name,
            document_id=state["resolved"].doc_id,
            artifact_path=state["artifact"],
            config=review_config,
            template=state["resolved"].template,
            policy=ctx.policy or PipelinePolicy(PipelineMode.draft),
            rebuild=lambda output: state["renderer"].build(
                state["resolved"].doc_id, state["config"], output=output
            ),
            scratch_dir=ctx.document_root / "runs" / "v2-review" / name,
        )
        # The completion record hashes the artifact, so build it only on success.
        completion = _successful_stage_result(name, state["artifact"]) if outcome.ok else None
        if completion is not None and not outcome.warnings:
            return completion
        return StageResult(
            name,
            outcome.ok,
            artifacts=completion.artifacts if completion is not None else (),
            warnings=outcome.warnings,
            errors=outcome.errors,
        )
