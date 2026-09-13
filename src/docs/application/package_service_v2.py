"""Deterministic, atomic ZIP publication for verified V2 package inputs."""

from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path


class PackagePublicationError(ValueError):
    """Raised when a package archive cannot be safely published."""


@dataclass(frozen=True)
class PackageFileV2:
    """One already-validated package member and its immutable content."""

    relative_path: str
    content: bytes


class PackageServiceV2:
    """Write deterministic ZIP bytes and publish them through an atomic replace."""

    def __init__(
        self,
        *,
        lock: Callable[[Path], AbstractContextManager[None]],
        directory_guard: Callable[[Path], AbstractContextManager[None]],
    ) -> None:
        self._lock = lock
        self._directory_guard = directory_guard

    def write(
        self,
        output: Path,
        files: Iterable[PackageFileV2],
        *,
        lock_held: bool = False,
    ) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        with nullcontext() if lock_held else self._lock(output.with_name(output.name + ".lock")):
            self._write_locked(output, tuple(sorted(files, key=lambda file: file.relative_path)))

    def _write_locked(self, output: Path, files: tuple[PackageFileV2, ...]) -> None:
        if any(candidate.is_symlink() for candidate in (output.parent, *output.parent.parents)) or not output.parent.is_dir():
            raise PackagePublicationError(f"package refuses unsafe output parent: {output.parent}")
        parent_identity = _directory_identity(output.parent)
        previous_identity, previous_content = _output_snapshot(output)
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
        ) as handle:
            scratch = Path(handle.name)
        published = False
        try:
            _write_deterministic_zip(scratch, files)
            expected_digest = hashlib.sha256(scratch.read_bytes()).digest()
            _assert_directory_identity(output.parent, parent_identity, operation="publication")
            _assert_output_unchanged(output, previous_identity, previous_content)
            with self._directory_guard(output.parent):
                os.replace(scratch, output)
            published = True
            published_identity = os.stat(output, follow_symlinks=False)
            _assert_directory_identity(output.parent, parent_identity, operation="publication")
            if (
                not output.is_file()
                or output.is_symlink()
                or hashlib.sha256(output.read_bytes()).digest() != expected_digest
            ):
                raise PackagePublicationError("package post-publication verification failed")
        except Exception:
            if published:
                _rollback(
                    output,
                    parent_identity,
                    previous_content,
                    published_identity,
                    expected_digest,
                    directory_guard=self._directory_guard,
                )
            raise
        finally:
            scratch.unlink(missing_ok=True)


def _write_deterministic_zip(archive_path: Path, files: tuple[PackageFileV2, ...]) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=True) as archive:
        for package_file in files:
            info = zipfile.ZipInfo(package_file.relative_path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.create_version = 20
            info.extract_version = 20
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, package_file.content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _directory_identity(path: Path) -> tuple[int, int]:
    identity = os.stat(path, follow_symlinks=False)
    return identity.st_dev, identity.st_ino


def _assert_directory_identity(path: Path, expected: tuple[int, int], *, operation: str) -> None:
    if _directory_identity(path) != expected or path.is_symlink() or not path.is_dir():
        raise PackagePublicationError(f"package output parent changed during {operation}: {path}")


def _output_snapshot(output: Path) -> tuple[tuple[int, int] | None, bytes | None]:
    if not output.exists():
        return None, None
    if output.is_symlink() or not output.is_file():
        raise PackagePublicationError(f"package refuses unsafe output: {output.name}")
    content = output.read_bytes()
    identity = os.stat(output, follow_symlinks=False)
    return (identity.st_dev, identity.st_ino), content


def _assert_output_unchanged(
    output: Path, expected: tuple[int, int] | None, expected_content: bytes | None
) -> None:
    if expected is None:
        if output.exists():
            raise PackagePublicationError(f"package output changed before publication: {output.name}")
        return
    if output.is_symlink() or not output.is_file() or expected_content is None:
        raise PackagePublicationError(f"package output changed before publication: {output.name}")
    current = os.stat(output, follow_symlinks=False)
    if (current.st_dev, current.st_ino) != expected or output.read_bytes() != expected_content:
        raise PackagePublicationError(f"package output changed before publication: {output.name}")


def _rollback(
    output: Path,
    parent_identity: tuple[int, int],
    previous_content: bytes | None,
    published_identity: os.stat_result,
    expected_digest: bytes,
    *,
    directory_guard: Callable[[Path], AbstractContextManager[None]],
) -> None:
    _assert_directory_identity(output.parent, parent_identity, operation="rollback")
    current_identity = os.stat(output, follow_symlinks=False) if output.is_file() else None
    if (
        output.is_symlink()
        or current_identity is None
        or (current_identity.st_dev, current_identity.st_ino)
        != (published_identity.st_dev, published_identity.st_ino)
        or hashlib.sha256(output.read_bytes()).digest() != expected_digest
    ):
        return
    if previous_content is None:
        output.unlink(missing_ok=True)
        return
    rollback = output.with_name(f".{output.name}.rollback")
    rollback.write_bytes(previous_content)
    with directory_guard(output.parent):
        os.replace(rollback, output)
