"""Named application boundary for the remaining legacy pipeline orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.models.template import Template
from docs.domain.ports.document_renderer_port import DocumentRendererPort


class LegacyPipelineService:
    """Own the legacy pipeline entry point while its implementation migrates."""

    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline

    def run_pipeline(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        stage_set: str,
        repo_root: Path,
        strict: bool = False,
        renderer: DocumentRendererPort | None = None,
    ) -> dict[str, Any]:
        """Delegate unchanged to preserve the legacy stage contract."""
        return self._pipeline.run_pipeline(
            doc_id,
            template,
            config,
            stage_set,
            repo_root,
            strict=strict,
            renderer=renderer,
        )
