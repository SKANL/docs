from __future__ import annotations

from pathlib import Path

import pytest

from docs.sidecar.cursor_secret import load_or_create_cursor_secret


def test_secret_is_generated_once_and_reused(tmp_path: Path) -> None:
    first = load_or_create_cursor_secret(tmp_path)
    second = load_or_create_cursor_secret(tmp_path)

    assert first == second
    assert len(first) >= 32
    assert bytes.fromhex((tmp_path / ".docs" / "cursor.key").read_text().strip()) == first


def test_each_install_gets_its_own_secret(tmp_path: Path) -> None:
    assert load_or_create_cursor_secret(tmp_path / "a") != load_or_create_cursor_secret(tmp_path / "b")


def test_secret_file_is_not_group_or_world_accessible(tmp_path: Path) -> None:
    import os
    import stat

    load_or_create_cursor_secret(tmp_path)
    mode = stat.S_IMODE((tmp_path / ".docs" / "cursor.key").stat().st_mode)
    if os.name != "nt":  # Windows reports POSIX bits only approximately
        assert mode & 0o077 == 0


def test_unwritable_workspace_falls_back_to_an_ephemeral_secret(tmp_path: Path) -> None:
    # `.docs` is a FILE, so neither the read nor the write can succeed: startup must degrade
    # (cursors die on restart) rather than crash build_application.
    (tmp_path / ".docs").write_text("not a directory", encoding="utf-8")

    secret = load_or_create_cursor_secret(tmp_path)

    assert len(secret) >= 32


def test_secret_length_is_the_one_the_api_enforces(tmp_path: Path) -> None:
    from docs.api.http import CURSOR_SECRET_BYTES, set_cursor_secret

    assert len(load_or_create_cursor_secret(tmp_path)) == CURSOR_SECRET_BYTES
    with pytest.raises(ValueError):
        set_cursor_secret(b"x" * (CURSOR_SECRET_BYTES - 1))


def test_truncated_secret_file_is_replaced(tmp_path: Path) -> None:
    key = tmp_path / ".docs" / "cursor.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"short")

    secret = load_or_create_cursor_secret(tmp_path)

    assert len(secret) >= 32
    assert bytes.fromhex(key.read_text().strip()) == secret
