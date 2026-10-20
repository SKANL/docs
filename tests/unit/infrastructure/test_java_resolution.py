from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Any

import opendataloader_pdf.runner as odl_runner
import pytest

from docs.infrastructure.tools.java_resolution import java_on_path


def test_java_on_path_leaves_os_environ_untouched(tmp_path: Path) -> None:
    java = tmp_path / "jdk" / "bin" / "java.exe"
    before = dict(os.environ)

    with java_on_path(str(java)):
        assert dict(os.environ) == before

    assert dict(os.environ) == before


def test_subprocess_receives_augmented_path_and_is_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    java = tmp_path / "jdk" / "bin" / "java.exe"
    seen: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    original_module = odl_runner.subprocess

    with java_on_path(str(java)):
        odl_runner.run_jar(["x"], quiet=True)

    assert seen["env"]["PATH"].split(os.pathsep)[0] == str(java.parent)
    assert os.environ["PATH"].split(os.pathsep)[0] != str(java.parent)
    assert odl_runner.subprocess is original_module


def test_overlapping_contexts_restore_the_real_subprocess(tmp_path: Path) -> None:
    # Two concurrent conversions (threaded sidecar): the 2nd used to save the 1st's wrapper as its
    # "original" and restore it last, leaving the library pinned to a stale environment snapshot.
    original_module = odl_runner.subprocess
    first_in, second_started, first_done = threading.Event(), threading.Event(), threading.Event()

    def first() -> None:
        with java_on_path(str(tmp_path / "a" / "java")):
            first_in.set()
            second_started.wait(5)
            threading.Event().wait(0.2)  # give the 2nd every chance to overlap
        first_done.set()

    def second() -> None:
        first_in.wait(5)
        second_started.set()
        with java_on_path(str(tmp_path / "b" / "java")):
            first_done.wait(1)  # the 1st leaves while the 2nd is (unserialised) still inside

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert not any(thread.is_alive() for thread in threads)
    assert odl_runner.subprocess is original_module


def test_nested_contexts_on_one_thread_do_not_deadlock(tmp_path: Path) -> None:
    original_module = odl_runner.subprocess
    done = threading.Event()

    def nested() -> None:
        with java_on_path(str(tmp_path / "a" / "java")), java_on_path(str(tmp_path / "b" / "java")):
            pass
        done.set()

    worker = threading.Thread(target=nested, daemon=True)
    worker.start()
    worker.join(5)

    assert done.is_set() and not worker.is_alive()
    assert odl_runner.subprocess is original_module


def test_a_context_stuck_in_another_thread_times_out_instead_of_blocking_forever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from docs.infrastructure.tools import java_resolution

    monkeypatch.setattr(java_resolution, "_SWAP_TIMEOUT", 0.2)
    holding, release = threading.Event(), threading.Event()

    def hold() -> None:
        with java_on_path(str(tmp_path / "a" / "java")):
            holding.set()
            release.wait(10)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert holding.wait(5)
    try:
        with pytest.raises(TimeoutError), java_on_path(str(tmp_path / "b" / "java")):
            pass
    finally:
        release.set()
        holder.join(5)
    assert not holder.is_alive()
