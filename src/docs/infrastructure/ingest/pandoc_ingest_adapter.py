# src/docs/infrastructure/ingest/pandoc_ingest_adapter.py
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from docs.domain.ingest_naming import ingested_output_path, sha256_hex
from docs.domain.ports.tool_resolver_port import ToolResolverPort
from docs.infrastructure.ingest.atomic_ingest_write import atomic_finalize, scratch_dir

# pandoc's reader identifiers already match this harness's `kind` labels for
# every kind routed here — kept as an explicit map (rather than passing
# `kind` straight through to `-f`) so a future kind whose pandoc reader name
# diverges from its `kind` label has one place to add the mapping.
_READER_BY_KIND: dict[str, str] = {"docx": "docx", "odt": "odt"}


class PandocIngestAdapter:
    """`SourceIngestPort` implementation for DOCX/ODT sources: pandoc with
    `--extract-media`, producing Markdown plus a per-document media directory
    (document-ingest spec: `Type-Based Ingest Routing` scenario "DOCX/ODT
    routed to pandoc with media extraction"). Registered under both `"docx"`
    and `"odt"` in `IngestService`'s handler table.

    `kind` is the value `IngestService` already resolved via the detector —
    NOT re-derived from `src`'s own extension (fresh-review FINDING 1): a
    source with a misleading extension (e.g. a real DOCX saved as `.doc`)
    must still convert correctly, so pandoc is given an explicit `-f`
    reader mapped from `kind` and never left to infer the input format from
    the filename itself."""

    def __init__(self, tool_resolver: ToolResolverPort, paths: dict[str, Any] | None = None) -> None:
        self.tool_resolver = tool_resolver
        self.paths = paths or {}

    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        src = Path(src)
        out_dir = Path(out_dir)
        pandoc = self.tool_resolver.resolve_pandoc(self.paths)
        if not pandoc:
            raise RuntimeError(
                "Pandoc no está disponible en PATH. Instálalo para ingerir archivos DOCX/ODT."
            )

        reader = _READER_BY_KIND.get(kind, kind)
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
                    "-f",
                    reader,
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
            final_media_dir = out_dir / media_dirname
            if tmp_media.exists():
                if final_media_dir.exists():
                    # Retry-safety (fresh-review FINDING 2): IngestService's
                    # skip-check already confirmed `final_md` is absent
                    # before `ingest()` was ever called, so any media dir
                    # already sitting at this exact content-addressed path
                    # must be an orphan left by an earlier attempt that
                    # finalized the media dir but died before the paired
                    # `.md` landed — safe to discard and replace, otherwise
                    # `os.replace` onto a non-empty directory would raise
                    # and the retry could never converge.
                    shutil.rmtree(final_media_dir)
                atomic_finalize(tmp_media, final_media_dir)
            atomic_finalize(tmp_md, final_md)

        return final_md
