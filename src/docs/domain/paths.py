"""The one path-confinement rule: a path must resolve inside its root."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath


class PathEscapeError(ValueError):
    """A path leaves the root it must stay inside. Callers map it to their own error code."""


def is_within(path: Path, root: Path, *, strict: bool = False) -> bool:
    """True when `path` resolves to `root` or something below it."""
    return path.resolve(strict=strict).is_relative_to(root.resolve(strict=strict))


def require_within(path: Path, root: Path, *, strict: bool = False) -> Path:
    """Return `path` resolved, or raise PathEscapeError when it resolves outside `root`.

    With `strict=True` a missing path raises OSError instead, as `Path.resolve` does.
    """
    resolved = path.resolve(strict=strict)
    if not resolved.is_relative_to(root.resolve(strict=strict)):
        raise PathEscapeError(f"path escapes its root: {path.name}")
    return resolved


def confine(root: Path, relative: str | Path, *, strict: bool = False) -> Path:
    """Join a caller-supplied relative path onto `root`; refuse anything that is not plainly inside it.

    Both `/` and `\\` separators are parsed on every platform, so `..\\x` is refused on POSIX too.
    """
    text = str(relative)
    parts = PureWindowsPath(text)
    if not text.strip() or parts.anchor or parts.drive or ".." in parts.parts or Path(text).is_absolute():
        raise PathEscapeError(f"path must be relative and inside its root: {text!r}")
    return require_within(root / text, root, strict=strict)
