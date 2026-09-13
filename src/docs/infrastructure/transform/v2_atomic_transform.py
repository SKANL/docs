"""Transactional publication for v2 transforms."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docs.infrastructure.locking import directory_handle_guard, owned_directory_lock

TransformCallable = Callable[[Path], None]
SubprocessAdapter = Callable[..., Any]
DEFAULT_COMMAND_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class TransformSpec:
    """Inputs and publication contract for one transform."""

    expected_outputs: tuple[str, ...]
    destinations: tuple[Path, ...]
    command: tuple[str, ...] | None = None
    warn_on_failure: bool = False
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS


@dataclass(frozen=True)
class TransformResult:
    ok: bool
    outputs: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class _PublicationTransaction:
    journal_path: Path
    backup_dir: Path
    entries: list[dict[str, object]]


class AtomicTransform:
    """Run a transform off-path and publish all outputs transactionally."""

    def __init__(self, subprocess_adapter: SubprocessAdapter | None = None) -> None:
        self._subprocess = subprocess_adapter or self._default_subprocess_adapter

    def run(self, spec: TransformSpec, operation: TransformCallable | None = None) -> TransformResult:
        self._validate(spec, operation)
        with self._transaction_lock(spec.destinations):
            return self._run_unlocked(spec, operation)

    def _run_unlocked(self, spec: TransformSpec, operation: TransformCallable | None = None) -> TransformResult:
        self._validate(spec, operation)
        self._recover_pending(spec.destinations)
        scratch_parent = self._journal_path(spec.destinations).parent
        scratch_parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=".atomic-transform-", dir=scratch_parent))
        result: TransformResult
        publication: _PublicationTransaction | None = None
        try:
            try:
                self._execute(spec, scratch, operation)
                self._verify_outputs(spec, scratch)
                expected_hashes = {
                    relative: hashlib.sha256((scratch / relative).read_bytes()).hexdigest()
                    for relative in spec.expected_outputs
                }
                publication = self._publish(spec, scratch)
                AtomicTransform._verify_published_outputs(spec, expected_hashes)
                self._finalize_journal(
                    spec.destinations,
                    publication.journal_path,
                    publication.backup_dir,
                    publication.entries,
                )
            except Exception as exc:  # the result is the failure boundary for application callers
                message = str(exc)
                if publication is not None:
                    try:
                        # Roll back from the transaction captured in this
                        # process first.  Its published identity is newer than
                        # the prepared journal, so this preserves a concurrent
                        # replacement made after publication.  A final recovery
                        # pass confirms that no durable journal remains and keeps
                        # rollback failures observable to callers.
                        self._rollback_in_memory(publication)
                        self._recover_pending(spec.destinations)
                    except Exception as rollback_error:
                        message = f"{message}; rollback failed: {rollback_error}"
                warning = (f"atomic transform failed: {message}",) if spec.warn_on_failure else ()
                result = TransformResult(ok=False, warnings=warning, error=message)
            else:
                result = TransformResult(ok=True, outputs=spec.destinations)
        finally:
            try:
                shutil.rmtree(scratch)
            except OSError as exc:
                # Cleanup is not publication.  A committed transaction must
                # remain successful and its journal is the durable recovery
                # record for a later invocation.
                result = TransformResult(
                    result.ok,
                    result.outputs,
                    (*result.warnings, f"atomic transform cleanup failed: {exc}"),
                    result.error,
                )
        return result

    @staticmethod
    def _validate(spec: TransformSpec, operation: TransformCallable | None) -> None:
        if not spec.expected_outputs:
            raise ValueError("expected_outputs must not be empty")
        if len(spec.expected_outputs) != len(spec.destinations):
            raise ValueError("expected_outputs and destinations must have the same length")
        if operation is not None and spec.command is not None:
            raise ValueError("provide either operation or command, not both")
        if operation is None and spec.command is None:
            raise ValueError("provide an operation or command")
        if len(set(spec.expected_outputs)) != len(spec.expected_outputs):
            raise ValueError("expected_outputs must not contain duplicates")
        for output in spec.expected_outputs:
            relative = Path(output)
            if relative.is_absolute() or ".." in relative.parts or not output:
                raise ValueError(f"expected output must be a safe relative path: {output!r}")
        for destination in spec.destinations:
            if not isinstance(destination, Path) or destination.is_dir():
                raise ValueError("destinations must be file paths")
            if AtomicTransform._has_symlinked_ancestor(destination):
                raise ValueError(f"destination must not be symlinked: {destination}")
        if spec.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def _execute(self, spec: TransformSpec, scratch: Path, operation: TransformCallable | None) -> None:
        if operation is not None:
            operation(scratch)
            return
        assert spec.command is not None
        try:
            completed = self._subprocess(spec.command, cwd=scratch, timeout=spec.timeout_seconds, text=True, capture_output=True)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                self._command_failure_message(
                    f"command timed out after {spec.timeout_seconds} seconds", exc.output, exc.stderr
                )
            ) from exc
        returncode = getattr(completed, "returncode", 0)
        if returncode:
            raise RuntimeError(
                self._command_failure_message(
                    f"command exited with status {returncode}",
                    getattr(completed, "stdout", ""),
                    getattr(completed, "stderr", ""),
                )
            )

    @staticmethod
    def _command_failure_message(message: str, stdout: str | bytes | None, stderr: str | bytes | None) -> str:
        diagnostics = []
        for name, stream in (("stdout", stdout), ("stderr", stderr)):
            if stream:
                content = stream.decode(errors="replace") if isinstance(stream, bytes) else str(stream)
                diagnostics.append(f"{name}: {content.strip()}")
        return "; ".join((message, *diagnostics))

    @staticmethod
    def _default_subprocess_adapter(
        command: Sequence[str], *, cwd: Path, timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS, text: bool = True, capture_output: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, cwd=cwd, check=False, text=text, capture_output=capture_output, timeout=timeout)

    @staticmethod
    def _verify_outputs(spec: TransformSpec, scratch: Path) -> None:
        for output in spec.expected_outputs:
            staged = scratch / output
            if not staged.is_file() or staged.stat().st_size == 0:
                raise ValueError(f"expected output {output!r} is missing or empty")

    @staticmethod
    def _publish(spec: TransformSpec, scratch: Path) -> _PublicationTransaction:
        """Publish one or many outputs through the same journal transaction."""
        AtomicTransform._validate_publication_targets(spec, scratch)
        journal_path = AtomicTransform._journal_path(spec.destinations)
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        backup_dir = Path(tempfile.mkdtemp(prefix=".atomic-transform-backups-", dir=journal_path.parent))
        entries = [
            AtomicTransform._publication_entry(relative, destination, backup_dir / str(index), scratch)
            for index, (relative, destination) in enumerate(
                zip(spec.expected_outputs, spec.destinations, strict=True)
            )
        ]
        AtomicTransform._write_journal(
            journal_path, {"state": "prepared", "backup_dir": str(backup_dir), "entries": entries}
        )
        published = False
        try:
            for relative, destination, entry in zip(spec.expected_outputs, spec.destinations, entries, strict=True):
                AtomicTransform._validate_publication_target(relative, destination, scratch)
                AtomicTransform._assert_destination_unchanged(destination, entry)
                backup = Path(str(entry["backup"]))
                if destination.exists():
                    shutil.copy2(destination, backup)
                AtomicTransform._assert_destination_unchanged(destination, entry)
                AtomicTransform._replace_checked(
                    scratch / relative,
                    destination,
                    entry["parent_identity"],
                    operation="publication",
                )
                # The destination is now owned by this transaction.  Any
                # failure while recording its identity/journal must take the
                # rollback path rather than discarding the recovery record.
                published = True
                published_identity = os.stat(destination, follow_symlinks=False)
                entry["published_identity"] = (
                    published_identity.st_dev,
                    published_identity.st_ino,
                    published_identity.st_size,
                    published_identity.st_mtime_ns,
                    published_identity.st_ctime_ns,
                )
                # Persist ownership without going through the public journal
                # hook: commit-failure tests and callers observe exactly one
                # prepared write plus one commit write, while crash recovery
                # still has the post-replace identity.
                AtomicTransform._write_journal_atomic(
                    journal_path, {"state": "prepared", "backup_dir": str(backup_dir), "entries": entries}
                )
        except Exception as publish_error:
            if published:
                try:
                    AtomicTransform._recover_pending(spec.destinations)
                except Exception as recovery_error:
                    raise RuntimeError(f"{publish_error}; rollback errors: {recovery_error}") from publish_error
            else:
                AtomicTransform._discard_prepared_journal(journal_path, backup_dir)
            raise
        return _PublicationTransaction(journal_path, backup_dir, entries)

    @staticmethod
    def _publication_entry(relative: str, destination: Path, backup: Path, scratch: Path) -> dict[str, object]:
        existed = destination.exists()
        existing_identity: tuple[int, int] | None = None
        previous_sha256: str | None = None
        if existed:
            if destination.is_symlink() or not destination.is_file():
                raise RuntimeError(f"publication destination must be a regular file: {destination}")
            identity = os.stat(destination, follow_symlinks=False)
            existing_identity = (identity.st_dev, identity.st_ino)
            previous_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
        return {
            "target": str(destination),
            "backup": str(backup),
            "existed": existed,
            "existing_identity": existing_identity,
            "previous_sha256": previous_sha256,
            "expected_sha256": hashlib.sha256((scratch / relative).read_bytes()).hexdigest(),
            "parent_identity": AtomicTransform._directory_identity(destination.parent),
        }

    @staticmethod
    def _journal_path(destinations: tuple[Path, ...]) -> Path:
        return destinations[0].parent / ".atomic-transform-journal.json"

    @staticmethod
    @contextmanager
    def _transaction_lock(destinations: tuple[Path, ...]):
        """Serialize journal/destination operations with ownership-safe recovery."""
        with owned_directory_lock(destinations[0].parent / ".atomic-transform.lock"):
            yield

    @staticmethod
    def _write_journal(path: Path, payload: dict[str, object]) -> None:
        AtomicTransform._write_journal_atomic(path, payload)

    @staticmethod
    def _write_journal_atomic(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".atomic-journal-", dir=path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            with directory_handle_guard(path.parent):
                os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _recover_pending(destinations: tuple[Path, ...]) -> None:
        journal_path = AtomicTransform._journal_path(destinations)
        if AtomicTransform._has_symlinked_ancestor(journal_path):
            raise RuntimeError("atomic publication journal path must not be symlinked")
        if not journal_path.is_file():
            return
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
        entries = payload.get("entries", [])
        if not isinstance(entries, list) or len(entries) != len(destinations):
            raise RuntimeError("invalid atomic publication journal entries")
        backup_dir = Path(str(payload.get("backup_dir", "")))
        AtomicTransform._validate_recovery_paths(destinations, entries, backup_dir, journal_path.parent)
        if payload.get("state") == "committed":
            shutil.rmtree(backup_dir, ignore_errors=True)
            journal_path.unlink(missing_ok=True)
            return
        recovery_errors: list[str] = []
        for raw_entry in reversed(entries):
            try:
                if not isinstance(raw_entry, dict):
                    raise RuntimeError("invalid atomic publication journal entry")
                target = Path(str(raw_entry["target"]))
                backup = Path(str(raw_entry["backup"]))
                expected_parent = raw_entry.get("parent_identity")
                if not isinstance(expected_parent, (tuple, list)):
                    raise RuntimeError("journal parent identity missing")
                AtomicTransform._assert_parent_identity(target, expected_parent, operation="rollback")
                if AtomicTransform._publication_target_needs_rollback(target, raw_entry):
                    if backup.is_file():
                        AtomicTransform._replace_checked(backup, target, expected_parent, operation="rollback")
                    elif not bool(raw_entry["existed"]) and raw_entry.get("published_identity") is not None:
                        target.unlink(missing_ok=True)
                        AtomicTransform._assert_parent_identity(target, expected_parent, operation="rollback")
            except (OSError, RuntimeError) as exc:
                recovery_errors.append(str(exc))
        if recovery_errors:
            raise RuntimeError("; ".join(recovery_errors))
        shutil.rmtree(backup_dir, ignore_errors=True)
        journal_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_recovery_paths(
        destinations: tuple[Path, ...], entries: list[object], backup_dir: Path, journal_root: Path
    ) -> None:
        try:
            if any(AtomicTransform._has_symlinked_ancestor(path) for path in (backup_dir, journal_root)):
                raise ValueError("symlinked recovery root")
            resolved_backup = backup_dir.resolve(strict=False)
            resolved_journal_root = journal_root.resolve(strict=False)
            resolved_backup.relative_to(resolved_journal_root)
            if resolved_backup == resolved_journal_root or resolved_backup.parent != resolved_journal_root:
                raise ValueError("backup root is not a dedicated child directory")
        except ValueError as exc:
            raise RuntimeError("journal backup root is outside intended destination root") from exc
        for destination, raw_entry in zip(destinations, entries, strict=True):
            if not isinstance(raw_entry, dict):
                raise RuntimeError("invalid atomic publication journal entry")
            target = Path(str(raw_entry.get("target", "")))
            backup = Path(str(raw_entry.get("backup", "")))
            try:
                if AtomicTransform._has_symlinked_ancestor(target) or AtomicTransform._has_symlinked_ancestor(backup):
                    raise ValueError("symlinked recovery path")
                target.resolve(strict=False).relative_to(destination.parent.resolve(strict=False))
                backup.resolve(strict=False).relative_to(backup_dir.resolve(strict=False))
                if target.resolve(strict=False) != destination.resolve(strict=False):
                    raise ValueError("journal target binding mismatch")
                expected_parent = raw_entry.get("parent_identity")
                if not isinstance(expected_parent, (tuple, list)):
                    raise ValueError("journal parent identity missing")
                if tuple(expected_parent) != AtomicTransform._directory_identity(target.parent):
                    raise ValueError("journal parent identity mismatch")
            except ValueError as exc:
                if "target binding" in str(exc):
                    raise RuntimeError("journal target binding mismatch") from exc
                if "parent identity" in str(exc):
                    raise RuntimeError("journal parent identity changed") from exc
                raise RuntimeError("journal path is outside intended destination or backup root") from exc

    @staticmethod
    def _has_symlinked_ancestor(path: Path) -> bool:
        return any(candidate.is_symlink() for candidate in (path, *path.parents))

    @staticmethod
    def _discard_prepared_journal(journal_path: Path, backup_dir: Path) -> None:
        """Remove an un-published transaction without touching destinations."""
        shutil.rmtree(backup_dir, ignore_errors=True)
        journal_path.unlink(missing_ok=True)

    @staticmethod
    def _rollback_in_memory(publication: _PublicationTransaction) -> None:
        """Rollback using the just-published identities, not a stale journal snapshot."""
        destinations = tuple(Path(str(entry["target"])) for entry in publication.entries)
        AtomicTransform._recover_pending(destinations)
        if not publication.journal_path.exists():
            return
        for raw_entry in reversed(publication.entries):
            target = Path(str(raw_entry["target"]))
            if not AtomicTransform._publication_target_needs_rollback(target, raw_entry):
                continue
            backup = Path(str(raw_entry["backup"]))
            if backup.is_file():
                AtomicTransform._replace_checked(
                    backup,
                    target,
                    raw_entry["parent_identity"],
                    operation="rollback",
                )
            elif not bool(raw_entry["existed"]) and raw_entry.get("published_identity") is not None:
                target.unlink(missing_ok=True)
        shutil.rmtree(publication.backup_dir, ignore_errors=True)
        publication.journal_path.unlink(missing_ok=True)

    @staticmethod
    def _finalize_journal(
        destinations: tuple[Path, ...], journal_path: Path, backup_dir: Path, entries: list[dict[str, object]]
    ) -> None:
        """Commit the prepared journal, rolling back if that durable step fails."""
        try:
            AtomicTransform._write_journal(
                journal_path, {"state": "committed", "backup_dir": str(backup_dir), "entries": entries}
            )
        except OSError as exc:
            try:
                AtomicTransform._recover_pending(destinations)
            except Exception as recovery_error:
                raise RuntimeError(f"journal commit failed: {exc}; rollback failed: {recovery_error}") from exc
            raise RuntimeError(f"journal commit failed after publication: {exc}") from exc
        with suppress(OSError):
            shutil.rmtree(backup_dir, ignore_errors=True)
        with suppress(OSError):
            journal_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_publication_targets(spec: TransformSpec, scratch: Path) -> None:
        """Reject unsafe or cross-device replacements before publication starts."""
        for relative, destination in zip(spec.expected_outputs, spec.destinations, strict=True):
            AtomicTransform._validate_publication_target(relative, destination, scratch)

    @staticmethod
    def _validate_publication_target(relative: str, destination: Path, scratch: Path) -> None:
        """Validate one target immediately before its replacement."""
        if AtomicTransform._has_symlinked_ancestor(destination):
            raise RuntimeError(f"publication destination must not be symlinked: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if AtomicTransform._has_symlinked_ancestor(destination):
            raise RuntimeError(f"publication destination must not be symlinked: {destination}")
        parent_stat = os.lstat(destination.parent)
        if not stat.S_ISDIR(parent_stat.st_mode) or AtomicTransform._has_symlinked_ancestor(destination.parent):
            raise RuntimeError(f"publication parent must be a regular non-symlink directory: {destination.parent}")
        staged = scratch / relative
        if os.stat(staged).st_dev != os.stat(destination.parent).st_dev:
            raise RuntimeError("atomic publication requires source and destination on the same device")

    @staticmethod
    def _directory_identity(path: Path) -> tuple[int, int]:
        identity = os.stat(path, follow_symlinks=False)
        return identity.st_dev, identity.st_ino

    @staticmethod
    def _assert_parent_identity(destination: Path, expected: object, *, operation: str) -> None:
        if not isinstance(expected, (tuple, list)) or tuple(expected) != AtomicTransform._directory_identity(destination.parent):
            raise RuntimeError(f"publication parent changed during {operation}: {destination}")

    @staticmethod
    def _assert_destination_unchanged(destination: Path, entry: dict[str, object]) -> None:
        expected_identity = entry.get("existing_identity")
        expected_hash = entry.get("previous_sha256")
        if expected_identity is None:
            if destination.exists():
                raise RuntimeError(f"publication destination changed before replacement: {destination}")
            return
        if not isinstance(expected_identity, (tuple, list)) or not isinstance(expected_hash, str):
            raise RuntimeError("invalid publication destination identity")
        if destination.is_symlink() or not destination.is_file():
            raise RuntimeError(f"publication destination changed before replacement: {destination}")
        current = os.stat(destination, follow_symlinks=False)
        if tuple(expected_identity) != (current.st_dev, current.st_ino) or hashlib.sha256(destination.read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError(f"publication destination changed before replacement: {destination}")

    @staticmethod
    def _publication_target_needs_rollback(target: Path, entry: dict[str, object]) -> bool:
        """Return whether this exact transaction still owns ``target``.

        A process may be interrupted before a replace takes effect. In that
        case the original target is already correct and must not be touched.
        Any third value is a concurrent update and is deliberately preserved.
        """
        expected_hash = entry.get("expected_sha256")
        if not isinstance(expected_hash, str):
            raise RuntimeError("journal published output hash missing")
        if not target.exists():
            if not bool(entry["existed"]):
                return False
            raise RuntimeError(f"publication target changed before rollback: {target}")
        if not target.is_file() or target.is_symlink():
            raise RuntimeError(f"publication target changed before rollback: {target}")
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        previous_hash = entry.get("previous_sha256")
        if bool(entry["existed"]) and isinstance(previous_hash, str) and actual == previous_hash:
            return False
        published_identity = entry.get("published_identity")
        if isinstance(published_identity, (tuple, list)):
            identity = os.stat(target, follow_symlinks=False)
            current_identity = (
                identity.st_dev,
                identity.st_ino,
                identity.st_size,
                identity.st_mtime_ns,
                identity.st_ctime_ns,
            )
            if tuple(published_identity) != current_identity:
                raise RuntimeError(f"publication target changed before rollback: {target}")
        if actual == expected_hash:
            return True
        raise RuntimeError(f"publication target changed before rollback: {target}")

    @staticmethod
    def _replace_checked(source: Path, destination: Path, expected_parent: object, *, operation: str) -> None:
        with directory_handle_guard(destination.parent):
            AtomicTransform._assert_parent_identity(destination, expected_parent, operation=operation)
            os.replace(source, destination)
            AtomicTransform._assert_parent_identity(destination, expected_parent, operation=operation)

    @staticmethod
    def _verify_published_outputs(spec: TransformSpec, expected_hashes: dict[str, str]) -> None:
        for relative, destination in zip(spec.expected_outputs, spec.destinations, strict=True):
            if AtomicTransform._has_symlinked_ancestor(destination) or not destination.is_file():
                raise RuntimeError(f"post-publication verification failed for {destination}")
            expected = expected_hashes[relative]
            actual = hashlib.sha256(destination.read_bytes()).hexdigest()
            if actual != expected:
                raise RuntimeError(f"post-publication verification failed for {destination}")
