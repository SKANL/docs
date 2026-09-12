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
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


class AtomicTransform:
    """Run a transform off-path and publish all outputs transactionally."""

    def __init__(self, subprocess_adapter: SubprocessAdapter | None = None) -> None:
        self._subprocess = subprocess_adapter or self._default_subprocess_adapter

    def run(self, spec: TransformSpec, operation: TransformCallable | None = None) -> TransformResult:
        self._validate(spec, operation)
        self._recover_pending(spec.destinations)
        scratch_parent = self._journal_path(spec.destinations).parent
        scratch_parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=".atomic-transform-", dir=scratch_parent))
        result: TransformResult
        try:
            try:
                self._execute(spec, scratch, operation)
                self._verify_outputs(spec, scratch)
                publication_warnings = self._publish(spec, scratch)
            except Exception as exc:  # the result is the failure boundary for application callers
                message = str(exc)
                warning = (f"atomic transform failed: {message}",) if spec.warn_on_failure else ()
                result = TransformResult(ok=False, warnings=warning, error=message)
            else:
                result = TransformResult(ok=True, outputs=spec.destinations, warnings=publication_warnings)
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
    def _publish(spec: TransformSpec, scratch: Path) -> tuple[str, ...]:
        if len(spec.destinations) > 1:
            return AtomicTransform._publish_multi_output(spec, scratch)
        return AtomicTransform._publish_with_journal(spec, scratch)

    @staticmethod
    def _journal_path(destinations: tuple[Path, ...]) -> Path:
        return destinations[0].parent / ".atomic-transform-journal.json"

    @staticmethod
    def _write_journal(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".atomic-journal-", dir=path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _recover_pending(destinations: tuple[Path, ...], *, force_rollback: bool = False) -> None:
        journal_path = AtomicTransform._journal_path(destinations)
        if AtomicTransform._has_symlinked_ancestor(journal_path):
            raise RuntimeError("atomic publication journal path must not be symlinked")
        if not journal_path.is_file():
            return
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
        entries = payload.get("entries", [])
        if not isinstance(entries, list):
            raise RuntimeError("invalid atomic publication journal")
        if len(entries) != len(destinations):
            raise RuntimeError("invalid atomic publication journal entries")
        backup_dir = Path(str(payload.get("backup_dir", "")))
        AtomicTransform._validate_recovery_paths(destinations, entries, backup_dir, journal_path.parent)
        if payload.get("state") == "committed":
            shutil.rmtree(backup_dir, ignore_errors=True)
            journal_path.unlink(missing_ok=True)
            return
        recovery_errors: list[str] = []
        for entry in reversed(entries):
            try:
                if not isinstance(entry, dict):
                    raise RuntimeError("invalid atomic publication journal entry")
                target = Path(str(entry["target"]))
                backup = Path(str(entry["backup"]))
                if backup.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, target)
                elif not bool(entry["existed"]):
                    target.unlink(missing_ok=True)
            except (OSError, RuntimeError) as exc:
                recovery_errors.append(str(exc))
        if recovery_errors:
            raise RuntimeError("; ".join(recovery_errors))
        backup_dir = Path(str(payload["backup_dir"]))
        with suppress(OSError):
            shutil.rmtree(backup_dir, ignore_errors=True)
        journal_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_recovery_paths(
        destinations: tuple[Path, ...], entries: list[object], backup_dir: Path, journal_root: Path
    ) -> None:
        try:
            if any(AtomicTransform._has_symlinked_ancestor(path) for path in (backup_dir, journal_root)):
                raise ValueError("symlinked recovery root")
            backup_dir.resolve(strict=False).relative_to(journal_root.resolve(strict=False))
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
            except ValueError as exc:
                raise RuntimeError("journal path is outside intended destination or backup root") from exc

    @staticmethod
    def _has_symlinked_ancestor(path: Path) -> bool:
        return any(candidate.is_symlink() for candidate in (path, *path.parents))

    @staticmethod
    def _publish_multi_output(spec: TransformSpec, scratch: Path) -> tuple[str, ...]:
        AtomicTransform._validate_publication_targets(spec, scratch)
        journal_path = AtomicTransform._journal_path(spec.destinations)
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        backup_dir = Path(tempfile.mkdtemp(prefix=".atomic-transform-backups-", dir=journal_path.parent))
        entries = [
            {
                "target": str(destination),
                "backup": str(backup_dir / str(index)),
                "existed": destination.exists(),
                "expected_sha256": hashlib.sha256((scratch / relative).read_bytes()).hexdigest(),
            }
            for index, (relative, destination) in enumerate(zip(spec.expected_outputs, spec.destinations, strict=True))
        ]
        AtomicTransform._write_journal(journal_path, {"state": "prepared", "backup_dir": str(backup_dir), "entries": entries})
        try:
            for index, (relative, destination) in enumerate(zip(spec.expected_outputs, spec.destinations, strict=True)):
                AtomicTransform._validate_publication_target(relative, destination, scratch)
                backup = Path(str(entries[index]["backup"]))
                if destination.exists():
                    shutil.copy2(destination, backup)
                os.replace(scratch / relative, destination)
        except Exception as publish_error:
            try:
                AtomicTransform._recover_pending(spec.destinations, force_rollback=True)
            except Exception as recovery_error:
                raise RuntimeError(f"{publish_error}; rollback errors: {recovery_error}") from publish_error
            raise
        try:
            AtomicTransform._write_journal(
                journal_path, {"state": "committed", "backup_dir": str(backup_dir), "entries": entries}
            )
        except OSError as exc:
            return (f"atomic transform journal commit failed after publication: {exc}",)
        with suppress(OSError):
            shutil.rmtree(backup_dir, ignore_errors=True)
        with suppress(OSError):
            journal_path.unlink(missing_ok=True)
        return ()

    @staticmethod
    def _publish_with_journal(spec: TransformSpec, scratch: Path) -> tuple[str, ...]:
        destination = spec.destinations[0]
        AtomicTransform._validate_publication_targets(spec, scratch)
        journal_path = AtomicTransform._journal_path(spec.destinations)
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup_dir = Path(tempfile.mkdtemp(prefix=".atomic-transform-backups-", dir=destination.parent))
        entry = {
            "target": str(destination),
            "backup": str(backup_dir / "0"),
            "existed": destination.exists(),
            "expected_sha256": hashlib.sha256((scratch / spec.expected_outputs[0]).read_bytes()).hexdigest(),
        }
        AtomicTransform._write_journal(
            journal_path, {"state": "prepared", "backup_dir": str(backup_dir), "entries": [entry]}
        )
        if destination.exists():
            shutil.copy2(destination, Path(str(entry["backup"])))
        AtomicTransform._validate_publication_target(spec.expected_outputs[0], destination, scratch)
        os.replace(scratch / spec.expected_outputs[0], destination)
        try:
            AtomicTransform._write_journal(
                journal_path, {"state": "committed", "backup_dir": str(backup_dir), "entries": [entry]}
            )
        except OSError as exc:
            return (f"atomic transform journal commit failed after publication: {exc}",)
        with suppress(OSError):
            shutil.rmtree(backup_dir, ignore_errors=True)
        with suppress(OSError):
            journal_path.unlink(missing_ok=True)
        return ()

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
