# src/docs/infrastructure/ingest/pandoc_ingest_adapter.py
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from docs.domain.ingest_naming import ingested_output_path, sha256_hex
from docs.domain.ports.tool_resolver_port import ToolResolverPort
from docs.infrastructure.ingest.atomic_ingest_write import atomic_finalize, scratch_dir


class PandocIngestAdapter:
    """`SourceIngestPort` implementation for DOCX/ODT sources: pandoc with
    `--extract-media`, producing Markdown plus a per-document media directory
    (document-ingest spec: `Type-Based Ingest Routing` scenario "DOCX/ODT
    routed to pandoc with media extraction"). Registered under both `"docx"`
    and `"odt"` in `IngestService`'s handler table — `kind` is re-derived
    from the source's own extension since `SourceIngestPort.ingest` does not
    carry the detector's resolved kind (design.md contract)."""

    def __init__(self, tool_resolver: ToolResolverPort, paths: dict[str, Any] | None = None) -> None:
        self.tool_resolver = tool_resolver
        self.paths = paths or {}

    def ingest(self, src: Path, out_dir: Path) -> Path:
        src = Path(src)
        out_dir = Path(out_dir)
        pandoc = self.tool_resolver.resolve_pandoc(self.paths)
        if not pandoc:
            raise RuntimeError(
                "Pandoc no está disponible en PATH. Instálalo para ingerir archivos DOCX/ODT."
            )

        kind = src.suffix.lstrip(".").lower()
        sha8 = sha256_hex(src.read_bytes())[:8]
        final_md = ingested_output_path(out_dir, src.stem, kind, sha8)
        stem_tag = f"{src.stem}-{kind}-{sha8}"
        media_dirname = f"{stem_tag}_media"

        # Temp-then-atomic-rename (binding constraint carried from PR5
        # fresh-review round 2): pandoc runs entirely inside a scratch
        # directory under `out_dir`; only on success are the resulting
        # `.md` and (optional) media directory moved into their final,
        # deterministic locations. A failing/partial pandoc run never
        # touches `out_dir` directly, so `IngestService`'s idempotency
        # skip-check can never mistake a corrupt partial file for a
        # completed ingest.
        with scratch_dir(out_dir) as tmp_dir:
            subprocess.run(
                [
                    pandoc,
                    str(src.resolve()),
                    f"--extract-media={media_dirname}",
                    "-t",
                    "markdown",
                    "-o",
                    f"{stem_tag}.md",
                ],
                cwd=tmp_dir,
                check=True,
            )
            tmp_md = tmp_dir / f"{stem_tag}.md"
            tmp_media = tmp_dir / media_dirname
            if tmp_media.exists():
                atomic_finalize(tmp_media, out_dir / media_dirname)
            atomic_finalize(tmp_md, final_md)

        return final_md
