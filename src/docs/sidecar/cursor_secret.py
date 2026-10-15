"""Per-install secret that signs pagination cursors."""

from __future__ import annotations

import contextlib
import os
import secrets
from pathlib import Path

from docs.composition import atomic_write_text

_SECRET_BYTES = 32


def load_or_create_cursor_secret(workspace: Path) -> bytes:
    """Return the install's cursor secret, generating it atomically on first use.

    Cursors signed under the retired hardcoded constant (or any other secret) fail
    verification and are rejected as invalid; clients simply restart pagination.
    """
    # ponytail: no cross-process creation lock; the sidecar is the only writer. If a CLI ever
    # mints cursors too, take owned_directory_lock around creation.
    path = workspace / ".docs" / "cursor.key"
    with contextlib.suppress(OSError, ValueError):
        existing = bytes.fromhex(path.read_text(encoding="ascii").strip())
        if len(existing) >= _SECRET_BYTES:
            return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(_SECRET_BYTES)
    atomic_write_text(path, secret.hex())
    # Owner-only on POSIX; on Windows chmod only toggles read-only and the file inherits the
    # per-user ACL of the workspace's .docs directory.
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return secret
