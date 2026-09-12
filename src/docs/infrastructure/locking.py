"""Small, fail-closed inter-process locks for filesystem transactions."""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def owned_directory_lock(path: Path, *, timeout: float = 30.0, stale_after: float = 30.0) -> Iterator[None]:
    """Acquire an atomic-directory lease without deleting a live owner's path.

    A crashed owner leaves the directory behind, but a later owner first
    atomically renames that exact directory to a private quarantine name.  A
    delayed reclaimer can therefore never remove a newly-created lock at the
    original pathname.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    deadline = time.monotonic() + timeout
    while True:
        try:
            path.mkdir()
            (path / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "token": token, "created_at": time.time()}, sort_keys=True),
                encoding="utf-8",
            )
            break
        except FileExistsError:
            if _reclaim_stale(path, stale_after=stale_after):
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out acquiring lock: {path}") from None
            time.sleep(0.01)
    try:
        yield
    finally:
        try:
            owner = json.loads((path / "owner.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            owner = {}
        if owner.get("token") == token:
            shutil.rmtree(path, ignore_errors=True)


def _reclaim_stale(path: Path, *, stale_after: float) -> bool:
    try:
        owner = json.loads((path / "owner.json").read_text(encoding="utf-8"))
        pid = int(owner["pid"])
        created_at = float(owner["created_at"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        try:
            stale = time.time() - path.stat().st_mtime > stale_after
        except OSError:
            return False
        pid = None
        created_at = 0.0
        if not stale:
            return False
    if pid is not None and time.time() - created_at <= stale_after:
        return False
    if pid is not None:
        try:
            os.kill(pid, 0)
        except PermissionError:
            return False
        except OSError:
            pass
        else:
            return False
    quarantine = path.with_name(f".{path.name}.reclaim-{uuid.uuid4().hex}")
    try:
        os.replace(path, quarantine)
    except (FileExistsError, OSError):
        return False
    shutil.rmtree(quarantine, ignore_errors=True)
    return True


@contextmanager
def directory_handle_guard(path: Path) -> Iterator[None]:
    """Pin a Windows directory against rename while a path operation runs."""
    if os.name != "nt":
        yield
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateFileW(
        str(path), 0, 0x00000001 | 0x00000002, None, 3, 0x02000000, None
    )
    invalid = wintypes.HANDLE(-1).value
    if handle == invalid:
        raise OSError(ctypes.get_last_error(), f"unable to pin publication directory: {path}")
    try:
        yield
    finally:
        kernel32.CloseHandle(handle)
