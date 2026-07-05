from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SourceIngestPort(Protocol):
    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        """Convert `src` into a deterministic Markdown file under `out_dir`
        and return its path (document-ingest spec: `Type-Based Ingest
        Routing`). `kind` is the detector-resolved type `IngestService`
        already computed for `src` — the router's single source of
        identity for both output naming and any format-specific decision
        the adapter makes. Adapters MUST NOT re-derive kind from `src`'s own
        file extension: a misleading extension does not change what the
        detector determined the file actually is (fresh-review FINDING 1 —
        a real DOCX saved as `.doc` was previously routed correctly but then
        failed conversion because the adapter re-derived "doc" from the
        filename instead of using the already-resolved "docx")."""
        ...
