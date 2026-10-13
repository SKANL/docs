import os
from pathlib import Path

import pytest

from docs.infrastructure import atomic_write
from docs.infrastructure.atomic_write import atomic_write_bytes, atomic_write_text


def test_writes_creates_parents_and_replaces(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b.bin"
    atomic_write_bytes(target, b"one")
    atomic_write_bytes(target, b"two", fsync=True)
    assert target.read_bytes() == b"two"
    assert [p.name for p in target.parent.iterdir()] == ["b.bin"]


def test_text_has_no_newline_translation(tmp_path: Path) -> None:
    target = tmp_path / "t.txt"
    atomic_write_text(target, "a\nb\n")
    assert target.read_bytes() == b"a\nb\n"


def test_failure_keeps_old_content_and_removes_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "f"
    atomic_write_bytes(target, b"old")

    def boom(*_: object) -> None:
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["f"]


def test_permission_error_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real, calls = os.replace, []

    def flaky(source: Path, destination: Path) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("held open")
        real(source, destination)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(atomic_write, "_REPLACE_BACKOFF_SECONDS", 0)
    atomic_write_bytes(tmp_path / "f", b"x")
    assert len(calls) == 3 and (tmp_path / "f").read_bytes() == b"x"


def test_persistent_permission_error_surfaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_: object) -> None:
        raise PermissionError("held open")

    monkeypatch.setattr(os, "replace", denied)
    monkeypatch.setattr(atomic_write, "_REPLACE_BACKOFF_SECONDS", 0)
    with pytest.raises(PermissionError):
        atomic_write_bytes(tmp_path / "f", b"x")
    assert list(tmp_path.iterdir()) == []
