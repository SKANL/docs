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


def test_remove_lock_dir_retries_the_release_rename_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    real_replace = os.replace

    def flaky(source: Path, destination: Path) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("owner.json is open")
        real_replace(source, destination)

    lock = tmp_path / "x.lock"
    lock.mkdir()
    (lock / "owner.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(locking, "_rename", flaky)
    locking._remove_lock_dir(lock)
    assert calls["n"] == 3
    assert not lock.exists()
    assert not list(tmp_path.iterdir())


def test_a_failed_cleanup_never_touches_a_lock_a_contender_created_meanwhile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A partial rmtree (owner.json gone, directory stuck) used to leave an ownerless directory at
    # the lock path; a contender reclaims it, and the NEXT retry deleted the contender's lock.
    lock = tmp_path / "x.lock"
    lock.mkdir()
    (lock / "owner.json").write_text("{}", encoding="utf-8")
    real_rmtree = shutil.rmtree

    def stuck(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path) == lock:  # the lock path itself must never be rmtree'd
            raise AssertionError("rmtree on the live lock path")
        (Path(path) / "owner.json").unlink()
        if not kwargs.get("ignore_errors"):
            raise PermissionError("directory is busy")

    monkeypatch.setattr(locking.shutil, "rmtree", stuck)
    locking._remove_lock_dir(lock, attempts=3)
    assert not lock.exists()  # released at once: a contender may now take the path
    lock.mkdir()  # the contender
    (lock / "owner.json").write_text('{"token": "new"}', encoding="utf-8")
    monkeypatch.setattr(locking.shutil, "rmtree", real_rmtree)
    assert (lock / "owner.json").exists()


def test_remove_lock_dir_warns_when_it_cannot_release_and_ignores_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    lock = tmp_path / "busy.lock"
    lock.mkdir()

    def busy(source: Path, destination: Path) -> None:
        raise PermissionError("busy")

    monkeypatch.setattr(locking, "_rename", busy)
    with caplog.at_level("WARNING", logger=locking.__name__):
        locking._remove_lock_dir(lock, attempts=2)
    assert lock.exists()
    assert any("busy.lock" in record.getMessage() for record in caplog.records)

    def gone(source: Path, destination: Path) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(locking, "_rename", gone)
    caplog.clear()
    locking._remove_lock_dir(tmp_path / "gone.lock")
    assert not caplog.records


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


def test_persistent_permission_error_fails_fast_as_permission_error(tmp_path: Path, monkeypatch) -> None:
    # PermissionError is only a transient Windows mid-delete signal; a real denial must surface as
    # itself within the short grace, not masquerade as a 30 s TimeoutError.
    real_mkdir = Path.mkdir

    def denied(self: Path, *args: object, **kwargs: object) -> None:
        if self.name == "denied.lock":
            raise PermissionError("access denied")
        real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", denied)
    started = time.monotonic()
    with pytest.raises(PermissionError), owned_directory_lock(tmp_path / "denied.lock", timeout=30):
        pass
    assert time.monotonic() - started < 10


def test_a_short_permission_error_is_retried_and_a_contention_resets_the_grace(tmp_path: Path, monkeypatch) -> None:
    real_mkdir = Path.mkdir
    outcomes = iter([PermissionError("deleting"), FileExistsError(), PermissionError("deleting")])

    def flaky(self: Path, *args: object, **kwargs: object) -> None:
        if self.name == "grace.lock":
            outcome = next(outcomes, None)
            if outcome is not None:
                raise outcome
        real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", flaky)
    with owned_directory_lock(tmp_path / "grace.lock", timeout=5, permission_grace=0.0001):
        pass  # the FileExistsError reset the grace window, so the 2nd denial did not raise
    assert not (tmp_path / "grace.lock").exists()
