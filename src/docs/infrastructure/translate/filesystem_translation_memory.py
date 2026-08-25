# src/docs/infrastructure/translate/filesystem_translation_memory.py
"""Content-addressed translation memory on disk.

An LLM is not deterministic -- batching, model versions and tie-breaks all
move the output -- but this harness requires byte-identical reruns. The cache
is what supplies that: the first run translates and stores, every later run is
a hit and reproduces the same bytes for free.

Writes reuse `infrastructure/ingest/atomic_ingest_write.py` rather than
re-declaring a temp-then-rename dance here. Same constraint as ingest, same
reason: an interrupted write must never leave a partial entry that a later run
reads back as a real translation.
"""
from __future__ import annotations

import json
from pathlib import Path

from docs.infrastructure.ingest.atomic_ingest_write import atomic_finalize, scratch_dir

_ENTRY_SUFFIX = ".json"


class FilesystemTranslationMemory:
    """`TranslationMemoryPort` over one directory of JSON entries."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path_for(self, key: str) -> Path:
        return self._root / f"{key}{_ENTRY_SUFFIX}"

    def get(self, key: str) -> str | None:
        path = self._path_for(key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return str(payload["translation"])
        except (json.JSONDecodeError, KeyError, OSError, UnicodeDecodeError):
            # A corrupt entry is a cache MISS, never a crash: the run
            # retranslates and overwrites it. Raising here would let one bad
            # byte on disk take down every future translation of that block.
            return None

    def put(self, key: str, source_text: str, translation: str) -> None:
        final = self._path_for(key)
        # `source` is stored for auditability only -- nothing reads it back.
        # `sort_keys` keeps the entry byte-identical across runs.
        payload = json.dumps(
            {"source": source_text, "translation": translation},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        with scratch_dir(self._root) as tmp_dir:
            staged = tmp_dir / f"entry{_ENTRY_SUFFIX}"
            staged.write_text(payload + "\n", encoding="utf-8")
            atomic_finalize(staged, final)
