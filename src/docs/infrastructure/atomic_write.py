"""The one temp-then-rename file writer.

Every adapter that publishes a single file atomically goes through here: the temp file lives in the
destination's own directory (same filesystem, so `os.replace` is a true atomic rename) and is
removed on any failure, leaving the previous file untouched.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

_REPLACE_ATTEMPTS = 50
_REPLACE_BACKOFF_SECONDS = 0.02


def _replace(source: Path, destination: Path) -> None:
    # ponytail: bounded retry for another PROCESS holding the destination open on Windows
    # (the CLI and the sidecar share files); ceiling ~1s, then the PermissionError surfaces.
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_SECONDS)


def fsync_directory(directory: Path) -> None:
    """Best-effort durable publish of a directory entry; platforms that cannot open a directory skip it."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes, *, fsync: bool = False) -> None:
    """Write `data` to `path` atomically, creating parent directories.

    `fsync` flushes the file and then the directory entry, so the new file survives a crash.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            if fsync:
                stream.flush()
                os.fsync(stream.fileno())
        _replace(temporary, path)
        if fsync:
            fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8", fsync: bool = False) -> None:
    """`atomic_write_bytes` for text; no newline translation, so output is identical on every platform."""
    atomic_write_bytes(path, text.encode(encoding), fsync=fsync)
