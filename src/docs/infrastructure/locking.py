"""Small, fail-closed inter-process locks for filesystem transactions."""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_log = logging.getLogger(__name__)
# Bound at import: lock release must not be hijacked by code (or tests) that patches the global `os.replace`.
_rename = os.replace


@contextmanager
def owned_directory_lock(
    path: Path, *, timeout: float = 30.0, stale_after: float = 30.0, permission_grace: float = 2.0
) -> Iterator[None]:
    """Acquire an atomic-directory lease without deleting a live owner's path.

    A crashed owner leaves the directory behind, but a later owner first
    atomically renames that exact directory to a private quarantine name.  A
    delayed reclaimer can therefore never remove a newly-created lock at the
    original pathname.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    deadline = time.monotonic() + timeout
    denied_since: float | None = None
    while True:
        try:
            path.mkdir()
            (path / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "token": token, "created_at": time.time()}, sort_keys=True),
                encoding="utf-8",
            )
            break
        except (FileExistsError, PermissionError) as error:
            # Windows reports a lock directory that a releasing owner is still
            # deleting as access denied, not as existing, so a PermissionError
            # is retried like contention. Trade-off: a genuine denial (ACL,
            # read-only parent) looks identical, so only a short continuous
            # grace is allowed before it is raised as itself rather than
            # surfacing as a misleading `timeout`-long TimeoutError.
            if isinstance(error, PermissionError):
                denied_since = denied_since if denied_since is not None else time.monotonic()
                if time.monotonic() - denied_since >= permission_grace:
                    raise
            else:
                denied_since = None
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
            _remove_lock_dir(path, token=token)


def _remove_lock_dir(path: Path, *, token: str, attempts: int = 200) -> None:
    """Release a lock by atomically renaming it away, then deleting the private copy.

    Deleting the lock path in place could leave an ownerless directory there after
    a partial `rmtree` (Windows: `owner.json` removed, directory still busy); a
    contender would reclaim that path and a later retry would delete ITS lock.
    The rename is the release: it is atomic, fails while a reader holds `owner.json`
    open (retried, `attempts` x 10 ms = 2 s by default), and afterwards the lock
    path is free while only this call touches the quarantine.
    """
    quarantine = path.with_name(f".{path.name}.release-{uuid.uuid4().hex}")
    for _ in range(attempts):
        try:
            _rename(path, quarantine)
            break
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.01)
    else:
        # We are a live pid, so the lock could never age out as "stale": mark it released so the
        # next acquirer reclaims it at once (or, failing even that, strip the owner so it ages out).
        outcome = _mark_released(path, token)
        if outcome == "marked":
            _log.warning("could not release lock %s after %d attempts; marked it reclaimable", path, attempts)
        elif outcome == "foreign":
            _log.debug("could not release lock %s after %d attempts; it now belongs to another owner, left untouched", path, attempts)
        else:
            _log.warning("could not release lock %s after %d attempts, nor mark it reclaimable; it ages out by mtime", path, attempts)
        return
    # Best effort: the lock is already released, a leftover quarantine blocks nobody.
    shutil.rmtree(quarantine, ignore_errors=True)


def _mark_released(path: Path, token: str) -> str:
    """Mark the lock released only while `owner.json` still carries OUR token.

    If the path changed hands during the failed release, the new owner's lock must stay untouched.
    Residual window (ponytail: no cross-process CAS on a plain file): a reclaim plus a contender's
    acquire landing between the read below and the write; it needs a stale-reclaim of a live pid's
    lock inside microseconds, so it is accepted rather than guarded.

    Returns "marked", "foreign" (another owner, left untouched) or "failed" (neither the marker nor the unlink landed).
    """
    owner = path / "owner.json"
    try:
        if json.loads(owner.read_text(encoding="utf-8")).get("token") != token:
            return "foreign"
    except (OSError, ValueError, AttributeError):
        # Unreadable (e.g. already ownerless): fall through to the best-effort marker.
        pass
    try:
        owner.write_text(json.dumps({"released": True}), encoding="utf-8")
    except OSError:
        try:
            owner.unlink()  # ownerless: `_reclaim_stale` ages it out by mtime
        except OSError:
            return "failed"
    return "marked"


def pid_alive(pid: int) -> bool:
    """True when `pid` names a running process (conservative: unknown means alive).

    `os.kill(pid, 0)` is not usable on Windows: it reports an exited pid as alive,
    so a crashed owner's lock was never reclaimed.
    """
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_invalid_parameter = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # Only "no such pid" proves death; access denied etc. means it exists.
        return ctypes.get_last_error() != error_invalid_parameter  # type: ignore[attr-defined]
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _reclaim_stale(path: Path, *, stale_after: float) -> bool:
    try:
        owner = json.loads((path / "owner.json").read_text(encoding="utf-8"))
        if isinstance(owner, dict) and owner.get("released") is True:
            return _quarantine(path)
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
    if pid is not None and pid_alive(pid):
        return False
    return _quarantine(path)


def _quarantine(path: Path) -> bool:
    quarantine = path.with_name(f".{path.name}.reclaim-{uuid.uuid4().hex}")
    try:
        _rename(path, quarantine)
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

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
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
        get_last_error = ctypes.get_last_error  # type: ignore[attr-defined]
        raise OSError(
            get_last_error(), f"unable to pin publication directory: {path}"
        )
    try:
        yield
    finally:
        kernel32.CloseHandle(handle)
