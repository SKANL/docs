"""Render and verification stages of the document pipeline."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from docs.application.artifact_render_service import ArtifactRenderService
from docs.application.document_pipeline_context import PipelineContext, stage_success
from docs.application.document_pipeline_verifiers import _verify_non_docx_artifact
from docs.domain.review import ReviewResult


def _directory_identity(path: Path) -> tuple[int, int]:
    identity = os.stat(path, follow_symlinks=False)
    return identity.st_dev, identity.st_ino


def _assert_directory_identity(path: Path, expected: tuple[int, int], *, operation: str) -> None:
    if _directory_identity(path) != expected or path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"package output parent changed during {operation}: {path}")


class BuildStages:
    """Render the primary artifact, alternate formats, and format-level checks."""

    def __init__(
        self,
        ctx: PipelineContext,
        artifact_renderer: ArtifactRenderService,
        build_token: str,
    ) -> None:
        self._ctx = ctx
        self._artifact_renderer = artifact_renderer
        self._build_token = build_token

    def build_with_format(self, format_name: str) -> tuple[bool, str]:
        ctx = self._ctx
        renderers = getattr(ctx.deps, "renderers", {})
        outcome = self._artifact_renderer.build_format(
            renderers=renderers if isinstance(renderers, Mapping) else {},
            format_name=format_name,
            document_id=ctx.state["resolved"].doc_id,
            config=ctx.state["config"],
            scratch_parent=ctx.document_root,
        )
        if outcome.scratch_dir is not None:
            ctx.scratch_dirs.append(outcome.scratch_dir)
        if outcome.succeeded and outcome.artifact is not None:
            ctx.state.setdefault("artifacts", {})[format_name] = outcome.artifact
        return outcome.succeeded, outcome.detail

    def render(self) -> tuple[bool, str]:
        ctx = self._ctx
        # The attested render is retained at one deterministic path per
        # document/format. This avoids unbounded random runs directories
        # while leaving the source available through package-release and
        # later provenance verification.
        runs_dir = ctx.document_root / "runs"
        outcome = self._artifact_renderer.render_and_retain(
            renderer=ctx.state["renderer"],
            format_name=ctx.output_format,
            document_id=ctx.state["resolved"].doc_id,
            config=ctx.state["config"],
            runs_dir=runs_dir,
            retained_dir=runs_dir / "v2-artifacts",
            build_token=self._build_token,
            directory_guard=ctx.deps.directory_guard,
            directory_identity=_directory_identity,
            assert_directory_identity=_assert_directory_identity,
        )
        if outcome.scratch_dir is not None:
            ctx.scratch_dirs.append(outcome.scratch_dir)
        if outcome.succeeded:
            ctx.state["artifact"] = outcome.artifact
            return stage_success("render", outcome.detail)
        return False, outcome.detail

    def audit(self) -> tuple[bool, str]:
        ctx = self._ctx
        state = ctx.state
        if ctx.output_format == "docx":
            result: ReviewResult = ctx.deps.format_audit.audit_format(
                state["artifact"], state["config"], strict=ctx.strict
            )
            state["verification"] = {"passed": result.passed, "format": ctx.output_format, "reopened": True}
            if not result.passed:
                return False, "; ".join(issue.message for issue in result.issues)
            return stage_success("audit")
        if ctx.output_format in {"html", "pdf"}:
            passed, detail = _verify_non_docx_artifact(ctx.output_format, state["artifact"])
            state["verification"] = {
                "passed": passed,
                "format": ctx.output_format,
                "reopened": True,
                "rendered": passed,
                "detail": detail,
            }
            return passed, detail
        return False, f"no format verifier is registered for {ctx.output_format}"

    def verify(self) -> tuple[bool, str]:
        ctx = self._ctx
        state = ctx.state
        if ctx.output_format != "docx":
            passed, detail = _verify_non_docx_artifact(ctx.output_format, state["artifact"])
            state["verification"] = {
                **state.get("verification", {}),
                "passed": passed,
                "format": ctx.output_format,
                "reopened": True,
                "readable": passed,
                "detail": detail,
            }
            return passed, detail
        qa_path = ctx.deps.qa.qa_docx(state["config"], state["artifact"], strict=ctx.strict)
        if ctx.strict and (qa_path is None or not Path(qa_path).exists()):
            return False, "strict verification requires durable QA evidence"
        if ctx.strict and Path(qa_path).is_dir() and not (Path(qa_path) / "qa-report.md").is_file():
            return False, "strict verification requires qa-report.md evidence"
        return stage_success("verify")
