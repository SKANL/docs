# src/docs/infrastructure/ingest/atomic_ingest_write.py
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def scratch_dir(out_dir: Path) -> Iterator[Path]:
    """A temp working directory created INSIDE `out_dir` (same filesystem,
    so the final `os.replace` below is a true atomic rename, not a
    cross-device copy) — always removed on exit, success or failure.

    Binding constraint (PR6 fresh-review carry-forward (a)): every ingest
    adapter must write its output outside the final `out_dir` first and only
    move it into place after conversion fully succeeds, so a mid-write
    failure never leaves a partial/corrupt file at the deterministic
    `<stem>-<kind>-<sha8>.md` path — otherwise `IngestService`'s idempotency
    skip-check would permanently treat the corrupt partial file as already
    ingested."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(dir=out_dir, prefix=".ingest-tmp-"))
    try:
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def atomic_finalize(tmp_path: Path, final_path: Path) -> Path:
    """Atomically move `tmp_path` (file or directory) to `final_path`. Both
    must live on the same filesystem (guaranteed when `tmp_path` was created
    via `scratch_dir(final_path.parent)`)."""
    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(str(tmp_path), str(final_path))
    return final_path
