from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from docs.infrastructure.locking import owned_directory_lock


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
