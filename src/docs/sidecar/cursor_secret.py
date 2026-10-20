"""Per-install secret that signs pagination cursors."""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
from pathlib import Path

from docs.api.http import CURSOR_SECRET_BYTES
from docs.composition import atomic_write_text

LOG = logging.getLogger(__name__)


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
        if len(existing) >= CURSOR_SECRET_BYTES:
            return existing
    secret = secrets.token_bytes(CURSOR_SECRET_BYTES)
    try:
        atomic_write_text(path, secret.hex())  # creates the missing parent directories
    except OSError:
        # An unwritable workspace degrades (cursors die on restart) instead of killing startup.
        LOG.warning("cursor key %s is not writable; using an ephemeral secret", path)
        return secret
    # Owner-only on POSIX; on Windows chmod only toggles read-only and the file inherits the
    # per-user ACL of the workspace's .docs directory.
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return secret
