from __future__ import annotations

import os
import subprocess
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
