from __future__ import annotations

import json
import os
import stat
import threading
import uuid
from pathlib import Path
from typing import Any

from docs.domain.contracts import Blob

_JSON = dict[str, Any]


class FilesystemBlobStore:
    """Blob store with fail-closed path checks and final-component no-follow reads.

    Portable pathlib checks cannot make a multi-step pathname lookup race-proof.
    We therefore reject symlinked ancestors when observed and use O_NOFOLLOW for
    the final opened file where the platform provides it; callers must treat a
    concurrent directory replacement as an explicit platform limitation.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("blob root cannot be a symlink")

    def put(self, blob: Blob, content: bytes) -> None:
        content_path, metadata_path = self._paths(blob.key)
        self._assert_safe_path(content_path)
        self._assert_safe_path(metadata_path)
        generation = uuid.uuid4().hex
        generation_dir = self._generation_dir(blob.key, generation)
        generation_content = generation_dir / "content"
        generation_metadata = generation_dir / "metadata.json"
        self._assert_safe_path(generation_dir)
        self._assert_safe_path(generation_content)
        self._assert_safe_path(generation_metadata)
        content_path.parent.mkdir(parents=True, exist_ok=True)
        generation_dir.mkdir(parents=True, exist_ok=False)
        self._atomic_write(generation_content, content)
        self._atomic_write(generation_metadata, (self._encode(blob.to_dict()) + "\n").encode("utf-8"))

        # Keep the original paths for callers that inspect the store directly.
        self._atomic_write(content_path, content)
        self._atomic_write(metadata_path, (self._encode(blob.to_dict()) + "\n").encode("utf-8"))
        self._atomic_write(
            self._manifest_path(blob.key),
            (self._encode({"generation": generation}) + "\n").encode("utf-8"),
        )

    def put_conditional(self, blob: Blob, content: bytes, *, expected_digest: str | None) -> bool:
        """Publish only when the current digest matches the expected value."""
        current = self.get(blob.key)
        if expected_digest is None:
            if current is not None:
                return False
        elif current is None or current[0].digest != expected_digest:
            return False
        self.put(blob, content)
        return True

    def compare_and_swap(self, key: str, expected_digest: str | None, blob: Blob, content: bytes) -> bool:
        if blob.key != key:
            raise ValueError("compare-and-swap key does not match blob key")
        return self.put_conditional(blob, content, expected_digest=expected_digest)

    def get(self, key: str) -> tuple[Blob, bytes] | None:
        content_path, metadata_path = self._paths(key)
        manifest_path = self._manifest_path(key)
        self._assert_safe_path(manifest_path)
        if self._is_regular_file(manifest_path):
            manifest = json.loads(self._read_safe(manifest_path))
            generation = manifest.get("generation") if isinstance(manifest, dict) else None
            if not isinstance(generation, str) or not generation or Path(generation).name != generation:
                raise ValueError("stored blob generation manifest is invalid")
            generation_dir = self._generation_dir(key, generation)
            content_path = generation_dir / "content"
            metadata_path = generation_dir / "metadata.json"
        self._assert_safe_path(content_path)
        self._assert_safe_path(metadata_path)
        if not self._is_regular_file(content_path) or not self._is_regular_file(metadata_path):
            return None
        blob = Blob.from_dict(json.loads(self._read_safe(metadata_path)))
        if blob.key != key:
            raise ValueError("stored blob key does not match requested key")
        return blob, self._read_safe_bytes(content_path)

    @staticmethod
    def _encode(value: _JSON) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def _paths(self, key: str) -> tuple[Path, Path]:
        candidate = Path(key)
        if not key or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("blob key must be a non-empty relative path without '..'")
        content_path = self.root / candidate
        metadata_path = content_path.with_name(content_path.name + ".json")
        root = self.root.resolve()
        for path in (content_path, metadata_path, self._manifest_path(key)):
            try:
                path.resolve(strict=False).relative_to(root)
            except ValueError as exc:
                raise ValueError("blob path must stay inside blob root (symlink or traversal detected)") from exc
        return content_path, metadata_path

    def _assert_safe_path(self, path: Path) -> None:
        root = self.root.resolve(strict=False)
        try:
            path.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise ValueError("blob path must stay inside blob root (symlink or traversal detected)") from exc
        current = path
        while current != current.parent:
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                current = current.parent
                continue
            if stat.S_ISLNK(mode):
                raise ValueError("blob path must stay inside blob root (symlink detected)")
            current = current.parent

    @staticmethod
    def _is_regular_file(path: Path) -> bool:
        try:
            return stat.S_ISREG(path.lstat().st_mode)
        except FileNotFoundError:
            return False

    @staticmethod
    def _read_safe(path: Path) -> str:
        return FilesystemBlobStore._read_safe_bytes(path).decode("utf-8")

    @staticmethod
    def _read_safe_bytes(path: Path) -> bytes:
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("blob path cannot be opened safely")
        except FileNotFoundError as exc:
            raise ValueError("blob path cannot be opened safely") from exc
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError as exc:
            raise ValueError("blob path cannot be opened safely") from exc
        try:
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                descriptor = -1
                return stream.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _manifest_path(self, key: str) -> Path:
        candidate = Path(key)
        return self.root / candidate.with_name(candidate.name + ".manifest")

    def _generation_dir(self, key: str, generation: str) -> Path:
        safe_key = key.replace("/", "\\")
        directory = self.root / ".generations" / safe_key / generation
        try:
            directory.resolve(strict=False).relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError("blob generation path must stay inside blob root (symlink or traversal detected)") from exc
        return directory

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        if path.is_symlink() or temporary.is_symlink() or path.parent.is_symlink():
            raise ValueError("blob path cannot be written through a symlink")
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
            except OSError:
                pass
            else:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
                finally:
                    os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
