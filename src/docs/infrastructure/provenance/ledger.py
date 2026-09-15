"""Filesystem-backed deterministic provenance ledger for v2 pipeline runs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from docs.domain.identity import canonical_json

_PROCESS_LOCK = threading.Lock()


class ProvenanceLedger:
    """Record and verify input and output hashes without touching legacy ledgers."""

    def __init__(self, log_path: Path, *, trusted_root: Path | None = None) -> None:
        self._log_path = log_path
        self._trusted_root = trusted_root.resolve() if trusted_root is not None else None

    def record_run(
        self,
        run_id: str,
        *,
        inputs: Iterable[Path],
        outputs: Iterable[Path],
        output_identities: Mapping[Path, Path] | None = None,
    ) -> dict[str, Any]:
        """Hash one run's inputs and outputs, then atomically persist its record."""
        identities = output_identities or {}
        record = {"run_id": run_id, "inputs": self._hashes(inputs)}
        record["outputs"] = self._hashes(outputs, identities)
        with self._lock():
            payload = self._load_payload()
            payload.setdefault("runs", {})[run_id] = record
            self._write_payload(payload)
        return record

    def load_run(self, run_id: str) -> dict[str, Any] | None:
        """Return a recorded run, if present."""
        return self._load_payload()["runs"].get(run_id)

    def record_attestation(self, run_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        """Durably record immutable build evidence before publication."""
        with self._lock():
            payload = self._load_payload()
            payload.setdefault("attestations", {})[run_id] = manifest
            self._write_payload(payload)
        return manifest

    def load_attestation(self, run_id: str) -> dict[str, Any] | None:
        return self._load_payload().get("attestations", {}).get(run_id)

    def verify_run(self, run_id: str, *, require_trusted_root: bool = False) -> bool:
        """Return whether every recorded input and output still matches its hash."""
        record = self.load_run(run_id)
        if record is None or (require_trusted_root and self._trusted_root is None):
            return False
        return self._verify_hashes(record["inputs"]) and self._verify_hashes(record["outputs"])

    def verify_attestation(self, run_id: str, manifest: dict[str, Any]) -> bool:
        """Require immutable attestation equality and a still-verifiable run."""
        return self.load_attestation(run_id) == manifest and self.verify_run(run_id)

    def _hashes(self, paths: Iterable[Path], identities: Mapping[Path, Path] | None = None) -> dict[str, str]:
        identities = identities or {}
        entries: list[tuple[str, Path]] = []
        for path in paths:
            if path.is_symlink():
                raise ValueError(f"provenance refuses symlinked path: {path}")
            if self._trusted_root is not None:
                try:
                    path.resolve(strict=True).relative_to(self._trusted_root)
                except (OSError, ValueError) as exc:
                    raise ValueError(f"provenance path is outside trusted root: {path}") from exc
            entries.append((self._stored_path(identities.get(path, path)), path))
        return {stored_path: self._hash_verified_path(path) for stored_path, path in sorted(entries)}

    def _stored_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self._log_path.parent.resolve()).as_posix()
        except ValueError:
            return str(path.resolve())

    def _verify_hashes(self, expected_hashes: dict[str, str]) -> bool:
        for name, expected_hash in expected_hashes.items():
            candidate = Path(name)
            # Ledger entries are data, not authority to follow arbitrary
            # symlinks or relative traversal paths during verification.
            if not candidate.is_absolute() and ".." in candidate.parts:
                return False
            path = candidate if candidate.is_absolute() else self._log_path.parent / candidate
            try:
                if self._trusted_root is not None:
                    path.resolve(strict=True).relative_to(self._trusted_root)
                if path.is_symlink() or not path.is_file() or not os.path.samefile(path, path.resolve()):
                    return False
                if self._hash_verified_path(path) != expected_hash:
                    return False
            except (OSError, ValueError):
                return False
        return True

    def _hash_verified_path(self, path: Path) -> str:
        """Hash the descriptor that passed root, type, and symlink checks."""
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"provenance requires a regular file: {path}")
        try:
            path.resolve(strict=True).relative_to(self._trusted_root or path.resolve(strict=True))
        except (OSError, ValueError) as exc:
            if self._trusted_root is not None:
                raise ValueError(f"provenance path is outside trusted root: {path}") from exc
        ancestors = tuple(
            (ancestor, os.stat(ancestor, follow_symlinks=False).st_ino, os.stat(ancestor, follow_symlinks=False).st_dev)
            for ancestor in (self._trusted_root, *path.parents)
            if ancestor is not None and ancestor.exists()
        )
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError(f"provenance requires a regular file: {path}")
            if any(
                (os.stat(ancestor, follow_symlinks=False).st_ino, os.stat(ancestor, follow_symlinks=False).st_dev)
                != (ino, dev)
                for ancestor, ino, dev in ancestors
            ):
                raise ValueError(f"provenance path boundary changed: {path}")
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            # Re-check every ancestor after consuming the descriptor.  The
            # descriptor pins the file bytes, while this closes the remaining
            # pathname/containment race for trusted-root policy decisions.
            if any(
                (os.stat(ancestor, follow_symlinks=False).st_ino, os.stat(ancestor, follow_symlinks=False).st_dev)
                != (ino, dev)
                for ancestor, ino, dev in ancestors
            ):
                raise ValueError(f"provenance path boundary changed while hashing: {path}")
            current = os.stat(path, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError(f"provenance file changed while hashing: {path}")
            return digest.hexdigest()
        finally:
            if descriptor != -1:
                os.close(descriptor)

    def _load_payload(self) -> dict[str, dict[str, dict[str, Any]]]:
        if not self._log_path.exists():
            return {"runs": {}, "attestations": {}}
        return json.loads(self._log_path.read_text(encoding="utf-8"))

    def _write_payload(self, payload: dict[str, dict[str, dict[str, Any]]]) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".provenance-v2-", suffix=".tmp", dir=self._log_path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(canonical_json(payload))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._log_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """Serialize read/merge/write updates without a third-party lock dependency."""
        with _PROCESS_LOCK:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self._log_path.with_name(self._log_path.name + ".lock")
            deadline = time.monotonic() + 10
            while True:
                try:
                    lock_path.mkdir()
                    (lock_path / "owner.json").write_text(
                        json.dumps({"pid": os.getpid(), "created_at": time.time()}, sort_keys=True),
                        encoding="utf-8",
                    )
                    break
                except FileExistsError:
                    if self._claim_stale_lock(lock_path):
                        try:
                            shutil.rmtree(lock_path)
                        except OSError as exc:
                            raise RuntimeError(f"unable to reclaim stale provenance lock: {lock_path}") from exc
                        continue
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"timed out acquiring provenance lock: {lock_path}") from None
                    time.sleep(0.01)
            try:
                yield
            finally:
                shutil.rmtree(lock_path, ignore_errors=True)

    @staticmethod
    def _stale_lock(lock_path: Path) -> bool:
        if (lock_path / ".reclaim").exists():
            return False
        try:
            owner = json.loads((lock_path / "owner.json").read_text(encoding="utf-8"))
            pid = int(owner["pid"])
            created_at = float(owner["created_at"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False

        if time.time() - created_at <= 30:
            return False
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return True
        except PermissionError:
            return False
        return False

    @staticmethod
    def _claim_stale_lock(lock_path: Path) -> bool:
        if not ProvenanceLedger._stale_lock(lock_path):
            return False
        try:
            (lock_path / ".reclaim").mkdir()
        except FileExistsError:
            return False
        except OSError:
            return False
        return True

