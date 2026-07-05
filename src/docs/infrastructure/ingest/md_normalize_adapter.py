# src/docs/infrastructure/ingest/md_normalize_adapter.py
from __future__ import annotations

import json
from pathlib import Path

from docs.domain.ingest_naming import ingested_output_path, sha256_hex
from docs.domain.markdown_text import split_frontmatter
from docs.infrastructure.ingest.atomic_ingest_write import atomic_finalize, scratch_dir


class MdNormalizeAdapter:
    """`SourceIngestPort` implementation for Markdown/TXT sources: reuses
    `split_frontmatter` (the same parser every section/context reader in
    this harness already trusts) to normalize any JSON frontmatter block
    into a canonical, sorted-key form and pass the body through untouched
    (document-ingest spec: `Type-Based Ingest Routing` scenario
    "Markdown/TXT normalized"). Registered under both `"md"` and `"txt"` in
    `IngestService`'s handler table. `kind` is the value `IngestService`
    already resolved via the detector (fresh-review FINDING 1) — NOT
    re-derived from the source's own extension, so a source whose extension
    disagrees with its detected kind is still named by what the router
    actually resolved."""

    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        src = Path(src)
        out_dir = Path(out_dir)
        sha8 = sha256_hex(src.read_bytes())[:8]
        final = ingested_output_path(out_dir, src.stem, kind, sha8)

        raw_text = src.read_text(encoding="utf-8")
        normalized = self._normalize(raw_text)

        # Temp-then-atomic-rename, same guarantee as every other PR6 ingest
        # adapter: nothing is written at `final` until the whole normalized
        # text is ready.
        with scratch_dir(out_dir) as tmp_dir:
            tmp_file = tmp_dir / final.name
            tmp_file.write_text(normalized, encoding="utf-8")
            atomic_finalize(tmp_file, final)

        return final

    def _normalize(self, raw_text: str) -> str:
        metadata, body = split_frontmatter(raw_text)
        if not metadata:
            # No frontmatter block, or an unparseable one — `split_frontmatter`
            # already falls back to returning the untouched raw text in
            # `body` for that case, so there is nothing left to normalize.
            return body
        canonical = json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2)
        return f"---\n{canonical}\n---\n{body}"
