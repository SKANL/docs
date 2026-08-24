from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class DocumentRendererPort(Protocol):
    """Contract any output-format renderer must satisfy.

    A concrete implementation (e.g. DOCX) is selected by a format-keyed
    registry at the composition root, resolved from the configured output
    format — domain/application code MUST NOT branch on format itself.
    """

    output_format: str

    def stage_plan(self) -> list[tuple[str, bool]]:
        """Ordered (stage-name, fail_fast) tuples for this format's assemble stage_set."""
        ...

    def build(self, doc_id: str, config: dict[str, Any], output: Path | None = None) -> Path | None:
        """Render the document and return the path to the produced artifact.

        `None` means the format degraded cleanly: its external toolchain is
        absent (pandoc for HTML, LibreOffice/soffice for PDF), the renderer
        already WARNed, and the pipeline reports the stage as skipped rather
        than failed. Callers MUST branch on `None` — `application/pipeline.py`
        (`stage_build_html`/`stage_build_pdf`) is the reference handling.
        """
        ...
