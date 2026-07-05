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

    def build(self, doc_id: str, config: dict[str, Any], output: Path | None = None) -> Path:
        """Render the document and return the path to the produced artifact."""
        ...
