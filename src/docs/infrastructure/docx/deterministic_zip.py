# src/docs/infrastructure/docx/deterministic_zip.py
from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

# python-docx (and docxcompose, which just delegates to `Document.save`) write
# every zip entry via `docx.opc.phys_pkg._ZipPkgWriter.write`, which calls
# `ZipFile.writestr(arcname, blob)` with a plain string `arcname` and no
# explicit `ZipInfo`. When `writestr` is given a string instead of a
# `ZipInfo`, the stdlib `zipfile` module builds one itself with
# `date_time=time.localtime(time.time())[:6]` -- the wall-clock time at the
# moment of the call, truncated to 2-second DOS timestamp granularity. Two
# builds of an otherwise byte-identical document normally land in the same
# 2-second window and compare equal, but under load (e.g. a full test suite
# run) the two builds can straddle a boundary, producing an intermittent
# byte-level diff that has nothing to do with document content. This
# harness's hard invariant is same inputs -> byte-identical outputs, so every
# finished `.docx` this adapter writes must have its zip entry timestamps
# normalized to a fixed sentinel as the last step before the file is
# considered complete.
SENTINEL_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def normalize_docx_zip_timestamps(docx_path: Path) -> None:
    """Rewrite every zip entry's `date_time` to a fixed sentinel value,
    leaving entry order, compression settings, and payload bytes untouched.

    Call this as the last step whenever a `.docx` file produced by this
    adapter is considered finished, so the on-disk artifact is fully
    deterministic across runs. Idempotent: calling it again on an
    already-normalized file is a no-op.
    """
    docx_path = Path(docx_path)
    with zipfile.ZipFile(docx_path, "r") as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]

    fd, tmp_name = tempfile.mkstemp(dir=str(docx_path.parent), prefix=".docx-normalize-", suffix=".docx")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp_path, "w") as archive:
            for info, data in entries:
                normalized = zipfile.ZipInfo(filename=info.filename, date_time=SENTINEL_DATE_TIME)
                normalized.compress_type = info.compress_type
                normalized.external_attr = info.external_attr
                normalized.create_system = info.create_system
                archive.writestr(normalized, data)
        tmp_path.replace(docx_path)
    finally:
        tmp_path.unlink(missing_ok=True)
