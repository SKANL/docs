from pathlib import Path

import pytest

from docs.domain.paths import PathEscapeError, confine, is_within, require_within


@pytest.mark.parametrize(
    "bad",
    ["", "  ", "../x", "a/../../x", "..\\x", "a\\..\\..\\x", "/abs/x", "\\abs\\x", "C:\\x", "C:x", "//srv/share/x"],
)
def test_confine_rejects_escapes(tmp_path: Path, bad: str) -> None:
    with pytest.raises(PathEscapeError):
        confine(tmp_path, bad)


def test_confine_accepts_nested_relative(tmp_path: Path) -> None:
    assert confine(tmp_path, "a/b.txt") == (tmp_path / "a" / "b.txt").resolve()
    assert confine(tmp_path, "a\\b.txt") == (tmp_path / "a" / "b.txt").resolve()


def test_escape_error_is_value_error() -> None:
    assert issubclass(PathEscapeError, ValueError)


def test_require_within_rejects_sibling_with_shared_prefix(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (tmp_path / "ws-evil").mkdir()
    root.mkdir()
    with pytest.raises(PathEscapeError):
        require_within(tmp_path / "ws-evil" / "f", root)
    assert not is_within(tmp_path / "ws-evil", root)
    assert is_within(root, root)
    assert require_within(root / "a" / ".." / "b", root) == (root / "b").resolve()


def test_require_within_strict_requires_existence(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        require_within(tmp_path / "missing", tmp_path, strict=True)
