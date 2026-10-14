"""Release-candidate promotion: commit a package only after publication succeeded."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer

from docs.composition import directory_handle_guard, owned_directory_lock
from docs.domain.identity import sha256_file


def promote_release_candidate(
    document_root: Path, document_id: str, *, allow_consumed_candidate: bool = False
) -> None:
    """Commit the package only after its format publication has succeeded."""
    release_dir = document_root / "output" / "release"
    candidate = release_dir / f".{document_id}.zip.candidate"
    destination = release_dir / f"{document_id}.zip"
    if not candidate.is_file() or candidate.is_symlink():
        if allow_consumed_candidate and destination.is_file() and not destination.is_symlink():
            # The publication transaction already committed this exact destination.
            # A concurrent/older final ZIP is never accepted because this path is only
            # used after the transaction has reported success.
            return
        raise RuntimeError("package-release completed without a safe release candidate")
    if any(path.is_symlink() for path in (release_dir, *release_dir.parents)):
        raise RuntimeError("release directory must not be symlinked")
    candidate_identity = os.stat(candidate, follow_symlinks=False)
    candidate_hash = sha256_file(candidate)
    with _package_lock(destination):
        parent_identity = _directory_identity(release_dir)
        _assert_directory_identity(release_dir, parent_identity, operation="release publication")
        current = os.stat(candidate, follow_symlinks=False)
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
            candidate_identity.st_dev,
            candidate_identity.st_ino,
            candidate_identity.st_size,
            candidate_identity.st_mtime_ns,
        ) or sha256_file(candidate) != candidate_hash:
            raise RuntimeError("release candidate changed before publication")
        with directory_handle_guard(release_dir):
            os.replace(candidate, destination)
        _assert_directory_identity(release_dir, parent_identity, operation="release publication")


def _directory_identity(path: Path) -> tuple[int, int]:
    identity = os.stat(path, follow_symlinks=False)
    return identity.st_dev, identity.st_ino


def _assert_directory_identity(path: Path, expected: tuple[int, int], *, operation: str) -> None:
    if _directory_identity(path) != expected or path.is_symlink() or not path.is_dir():
        raise typer.BadParameter(f"package output parent changed during {operation}: {path}")


@contextmanager
def _package_lock(output: Path) -> Iterator[None]:
    """Serialize existing release-package merge and publication transactions."""
    with owned_directory_lock(output.with_name(output.name + ".lock")):
        yield
