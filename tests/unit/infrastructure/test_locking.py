from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
