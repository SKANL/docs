from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docs.domain.cover import cover_provenance
from docs.domain.models.template import Template
from docs.domain.ports.document_renderer_port import DocumentRendererPort

if TYPE_CHECKING:
    from docs.application.pipeline import PipelineService


class LegacyPipelineExecutor:
    """Execute the legacy pipeline orchestration through a PipelineService collaborator."""

    def execute(
        self,
        pipeline: PipelineService,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        stage_set: str,
        repo_root: Path,
        strict: bool,
        renderer: DocumentRendererPort,
    ) -> dict[str, Any]:
        # Resolve through the application module at call time so the legacy
        # ``docs.application.pipeline.pipeline_stage_plan`` patch seam remains
        # effective without importing PipelineService during module loading.
        from docs.application import pipeline as pipeline_module

        stages = pipeline_module.pipeline_stage_plan(stage_set, renderer.stage_plan())
        callables = pipeline._stage_callables(doc_id, template, config, repo_root, strict, renderer)
        results: list[dict[str, Any]] = []
        passed = True
        for name, fail_fast in stages:
            started = datetime.now()
            try:
                ok, detail = callables[name]()
            except Exception as exc:
                # Include the exception type when a stage raises without a message.
                ok, detail = False, f"ERROR: {type(exc).__name__}: {exc}"
            duration = (datetime.now() - started).total_seconds()
            results.append({"stage": name, "ok": ok, "duration_s": round(duration, 3), "detail": detail})
            if not ok:
                passed = False
                if fail_fast:
                    break
        summary = {"stage_set": stage_set, "strict": strict, "passed": passed, "stages": results}
        cover = cover_provenance(config)
        if cover is not None:
            summary["cover"] = cover
        if stage_set in ("assemble", "all"):
            summary["build_version"] = pipeline._next_build_version(doc_id, config)
        pipeline.log_run(doc_id, config, repo_root, f"pipeline-{stage_set}", summary)
        return summary
