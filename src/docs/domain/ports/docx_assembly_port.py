from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class DocxAssemblyPort(Protocol):
    def render_pandoc(self, pandoc_path: str, inputs: list[Path], output: Path) -> None: ...

    def assemble(
        self,
        config: dict[str, Any],
        body_docx: Path,
        output_docx: Path,
        *,
        cover_asset_path: Path | None,
        embed_front_paths: list[Path],
        embed_back_paths: list[Path],
    ) -> None: ...
