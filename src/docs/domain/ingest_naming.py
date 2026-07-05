# src/docs/domain/ingest_naming.py
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_hex(data: bytes) -> str:
    """Canonical content-hash used to derive the deterministic ingested
    output name (document-ingest spec: `Deterministic and Idempotent
    Ingest`). Single source of truth shared by `IngestService` and every
    `SourceIngestPort` adapter, so both sides always agree on the same
    output path for the same source bytes."""
    return hashlib.sha256(data).hexdigest()


def ingested_output_path(out_dir: Path, stem: str, kind: str, sha8: str) -> Path:
    """Deterministic `<stem>-<kind>-<sha8>.md` path under `out_dir`. Identity
    is (stem, kind, content hash) — not just (stem, hash) — so two sources
    with the same stem and byte-identical bodies but different detected
    kinds (e.g. `readme.md` / `readme.txt`) never collide on one output
    path (PR5 fresh-review fix, reused here as the shared implementation)."""
    return Path(out_dir) / f"{stem}-{kind}-{sha8}.md"
