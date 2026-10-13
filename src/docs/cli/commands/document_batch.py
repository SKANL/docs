"""Crash-safe transaction around a batch build's `output/` directories."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from docs.domain.identity import sha256_file
from docs.infrastructure.locking import directory_handle_guard, owned_directory_lock

_BATCH_OUTPUT_PATHS = (Path("output") / "current", Path("output") / "release")


@dataclass(frozen=True)
class BatchTransaction:
    """Backup plus journal that let a failed or unsuccessful build be rolled back."""

    doc_id: str
    journal: Path
    backup: Path

    @classmethod
    def begin(cls, doc_id: str, root: Path) -> BatchTransaction:
        root.mkdir(parents=True, exist_ok=True)
        journal = _batch_journal_path(root)
        _recover_batch_transaction(journal, _lock_held=True)
        backup = Path(tempfile.mkdtemp(prefix=".docs-batch-", dir=root))
        for relative in _BATCH_OUTPUT_PATHS:
            current = root / relative
            if current.exists() and not current.is_symlink():
                shutil.copytree(current, backup / relative)
        _write_batch_journal(journal, root, backup, _BATCH_OUTPUT_PATHS)
        return cls(doc_id, journal, backup)

    def restore(self) -> None:
        _recover_batch_transaction(self.journal, _lock_held=True)

    def record(self, output_format: str) -> None:
        _record_batch_outputs(self.journal, self.doc_id, output_format)

    def finish(self, *, succeeded: bool) -> None:
        """Roll back an unsuccessful batch, then retire any remaining recovery evidence."""
        if not succeeded:
            self.restore()
        if self.journal.exists():
            self.journal.unlink()
            shutil.rmtree(self.backup)


def _batch_journal_path(root: Path) -> Path:
    return root / "runs" / "batch-transaction.json"


def _write_batch_journal(journal: Path, root: Path, backup: Path, paths: tuple[Path, ...]) -> None:
    journal.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "docs.batch/v1",
        "root": str(root.resolve()),
        "backup": str(backup.resolve()),
        "paths": [path.as_posix() for path in paths],
        "expected": {path.as_posix(): _batch_snapshot(root / path) for path in paths},
        "saved": {path.as_posix(): _batch_snapshot(backup / path) for path in paths},
    }
    temporary = journal.with_name(f".{journal.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, journal)


def _batch_snapshot(directory: Path) -> dict[str, list[object]]:
    if any(
        path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_reparse_tag", 0) != 0)
        for path in (directory, *directory.parents)
    ):
        raise RuntimeError("batch recovery refuses redirected paths")
    if not directory.exists():
        return {}
    if not directory.is_dir():
        raise RuntimeError("batch recovery output path must be a directory")
    snapshot: dict[str, list[object]] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_reparse_tag", 0) != 0):
            raise RuntimeError("batch recovery refuses redirected paths")
        if path.is_file():
            identity = path.stat()
            snapshot[path.relative_to(directory).as_posix()] = [
                sha256_file(path),
                identity.st_dev,
                identity.st_ino,
                identity.st_size,
                identity.st_mtime_ns,
                identity.st_ctime_ns,
            ]
        elif not path.is_dir():
            raise RuntimeError("batch recovery refuses non-regular paths")
    return snapshot


def _record_batch_outputs(journal: Path, doc_id: str, output_format: str) -> None:
    """Record only the known publication paths, never adopt unrelated outputs.

    A crash before this checkpoint fails closed: publication ownership cannot
    be inferred from a current batch journal or from unrecorded output bytes.
    """
    payload = json.loads(journal.read_text(encoding="utf-8"))
    owned = {
        "output/current": (f"{doc_id}.{output_format}", f"{doc_id}.{output_format}.manifest.json"),
        "output/release": (f"{doc_id}.zip",),
    }
    for relative, names in owned.items():
        current = _batch_snapshot(Path(payload["root"]) / relative)
        for name in names:
            if name in current:
                payload["expected"][relative][name] = current[name]
    temporary = journal.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(temporary, journal)


def _recover_batch_transaction(journal: Path, *, _lock_held: bool = False) -> None:
    if not journal.exists():
        return
    if not _lock_held:
        with owned_directory_lock(journal.parent / ".docs-batch.lock"):
            return _recover_batch_transaction(journal, _lock_held=True)
    payload = json.loads(journal.read_text(encoding="utf-8"))
    root = journal.parent.parent.resolve()
    backup = Path(payload["backup"])
    paths = _BATCH_OUTPUT_PATHS
    if (
        Path(payload["root"]).resolve() != root
        or journal.resolve() != _batch_journal_path(root)
        or backup.parent.resolve() != root
        or not backup.name.startswith(".docs-batch-")
        or payload.get("paths") != [path.as_posix() for path in paths]
    ):
        raise RuntimeError("batch recovery path scope is invalid")
    if not isinstance(payload.get("expected"), dict) or not isinstance(payload.get("saved"), dict):
        raise RuntimeError("batch recovery ownership unavailable; preserve journal for manual recovery")
    _batch_snapshot(backup)  # Validate all backup paths before touching any output.

    def checked_snapshot(relative: Path) -> dict[str, list[object]]:
        key = relative.as_posix()
        current = _batch_snapshot(root / relative)
        expected = payload["expected"][key]
        saved = payload["saved"][key]
        for name in current.keys() | expected.keys() | saved.keys():
            value = current.get(name)
            previous = saved.get(name)
            if value == expected.get(name) or (value is not None and previous is not None and value[0] == previous[0]):
                continue
            if value is None and previous is None:  # Already removed on a previous recovery attempt.
                continue
            raise RuntimeError(f"batch recovery output changed concurrently: {relative / name}")
        return current

    for relative in paths:
        if _batch_snapshot(backup / relative) != payload["saved"][relative.as_posix()]:
            raise RuntimeError("batch recovery backup changed")
        checked_snapshot(relative)
    # Copy first. A failed copy never removes a live output or consumes backups.
    with tempfile.TemporaryDirectory(prefix=".docs-batch-restore-", dir=root) as temporary:
        staged = Path(temporary)
        for relative in paths:
            saved_dir = backup / relative
            if saved_dir.exists():
                shutil.copytree(saved_dir, staged / relative)
        for relative in paths:
            current = checked_snapshot(relative)
            saved = payload["saved"][relative.as_posix()]
            for name in sorted(current.keys() | saved.keys()):
                checked_snapshot(relative)
                target = root / relative / name
                if name in saved:
                    if name in current and current[name][0] == saved[name][0]:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with directory_handle_guard(target.parent):
                        os.replace(staged / relative / name, target)
                else:
                    target.unlink(missing_ok=True)
    # Only a fully restored transaction can retire its recovery evidence.
    journal.unlink()
    shutil.rmtree(backup)
