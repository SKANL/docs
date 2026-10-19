from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from docs.infrastructure import locking
from docs.infrastructure.locking import owned_directory_lock, pid_alive


def test_contended_lock_is_always_released(tmp_path: Path) -> None:
    # On Windows a contender reading owner.json can make the owner's removal fail once; the lock
    # must still be released, otherwise every later acquirer times out.
    lock = tmp_path / "shared.lock"

    def work(_: int) -> None:
        with owned_directory_lock(lock, timeout=5):
            pass

    for _ in range(10):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(work, range(16)))
        assert not lock.exists()


def test_lock_of_exited_owner_is_reclaimed(tmp_path: Path) -> None:
    # os.kill(pid, 0) reports an exited pid as alive on Windows, so a crashed owner's lock
    # used to be unreclaimable. Use a real child process that has really exited.
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    lock = tmp_path / "crashed.lock"
    lock.mkdir()
    (lock / "owner.json").write_text(
        json.dumps({"pid": child.pid, "token": "dead", "created_at": time.time() - 3600}),
        encoding="utf-8",
    )

    with owned_directory_lock(lock, timeout=2, stale_after=1):
        owner = json.loads((lock / "owner.json").read_text(encoding="utf-8"))
        assert owner["pid"] == os.getpid()


def test_pid_alive_distinguishes_live_and_exited_processes() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert pid_alive(os.getpid()) is True
    assert pid_alive(child.pid) is False


def test_remove_lock_dir_retries_then_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    real_rmtree = shutil.rmtree

    def flaky(path: Path, *args: object, **kwargs: object) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("owner.json is open")
        real_rmtree(path)

    lock = tmp_path / "x.lock"
    lock.mkdir()
    monkeypatch.setattr(locking.shutil, "rmtree", flaky)
    locking._remove_lock_dir(lock)
    assert calls["n"] == 3
    assert not lock.exists()


def test_remove_lock_dir_gives_up_quietly_and_ignores_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []

    def always_busy(path: Path, *args: object, **kwargs: object) -> None:
        seen.append(kwargs.get("ignore_errors"))
        if not kwargs.get("ignore_errors"):
            raise PermissionError("busy")

    monkeypatch.setattr(locking.shutil, "rmtree", always_busy)
    locking._remove_lock_dir(tmp_path / "busy.lock", attempts=2)
    assert seen == [None, None, True]

    def gone(path: Path, *args: object, **kwargs: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(locking.shutil, "rmtree", gone)
    locking._remove_lock_dir(tmp_path / "gone.lock")


def test_pid_alive_uses_the_windows_probe_on_nt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(locking, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(locking, "_pid_alive_windows", lambda pid: pid == 7)
    assert locking.pid_alive(7) is True
    assert locking.pid_alive(8) is False


def _fake_kernel32(monkeypatch: pytest.MonkeyPatch, *, handle: int, exit_code: int, ok: bool = True, last_error: int = 0) -> MagicMock:
    import ctypes

    kernel32 = MagicMock()
    kernel32.OpenProcess.return_value = handle

    def get_exit_code(_handle: int, out: object) -> bool:
        out._obj.value = exit_code  # type: ignore[attr-defined]
        return ok

    kernel32.GetExitCodeProcess.side_effect = get_exit_code
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: kernel32, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: last_error, raising=False)
    return kernel32


def test_windows_probe_reports_running_and_exited_owners(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel32 = _fake_kernel32(monkeypatch, handle=1, exit_code=259)
    assert locking._pid_alive_windows(10) is True
    kernel32.CloseHandle.assert_called_once()
    _fake_kernel32(monkeypatch, handle=1, exit_code=0)
    assert locking._pid_alive_windows(10) is False
    _fake_kernel32(monkeypatch, handle=1, exit_code=0, ok=False)
    assert locking._pid_alive_windows(10) is True


def test_windows_probe_treats_only_an_invalid_pid_as_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_kernel32(monkeypatch, handle=0, exit_code=0, last_error=87)
    assert locking._pid_alive_windows(10) is False
    _fake_kernel32(monkeypatch, handle=0, exit_code=0, last_error=5)
    assert locking._pid_alive_windows(10) is True
