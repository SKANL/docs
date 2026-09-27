from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from docs.domain.runtime_records import Blob
from docs.infrastructure.persistence.filesystem_blob_store import FilesystemBlobStore


def test_filesystem_blob_store_round_trips_content_and_metadata(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path / "blobs")
    blob = Blob("reports/output.bin", "sha256:abc", 3, metadata={"source": "test"})

    store.put(blob, b"abc")

    reopened = FilesystemBlobStore(tmp_path / "blobs")
    assert reopened.get(blob.key) == (blob, b"abc")
    assert json.loads((tmp_path / "blobs" / "reports" / "output.bin.json").read_text()) == blob.to_dict()


def test_filesystem_atomic_write_fsyncs_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)

    FilesystemBlobStore(tmp_path / "blobs").put(Blob("report.bin", "sha256:report", 6), b"report")

    assert len(fsync_calls) >= 5


def test_filesystem_blob_store_rejects_symlinked_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    try:
        os.symlink(outside, root / "linked", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    store = FilesystemBlobStore(root)
    with pytest.raises(ValueError, match="inside blob root"):
        store.put(Blob("linked/escape.bin", "sha256:escape", 6), b"escape")


def test_filesystem_blob_store_rejects_symlinked_generation_ancestor_before_mkdir(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        os.symlink(outside, root / ".generations", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="symlink"):
        FilesystemBlobStore(root).put(Blob("report.bin", "sha256:report", 7), b"report")

    assert list(outside.iterdir()) == []


def test_filesystem_blob_store_reads_one_published_generation(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path / "blobs")
    first = Blob("report.bin", "sha256:first", 5)
    second = Blob("report.bin", "sha256:second", 6)

    store.put(first, b"first")
    store.put(second, b"second")
    (tmp_path / "blobs" / "report.bin").write_bytes(b"wrong-generation")
    (tmp_path / "blobs" / "report.bin.json").write_text(json.dumps(first.to_dict()))

    assert store.get("report.bin") == (second, b"second")


def test_filesystem_blob_store_compare_and_swap_is_atomic_at_the_contract_boundary(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path / "blobs")
    first = Blob("report.bin", "sha256:first", 5)
    second = Blob("report.bin", "sha256:second", 6)

    assert store.put_conditional(first, b"first", expected_digest=None) is True
    assert store.put_conditional(second, b"second", expected_digest="sha256:wrong") is False
    assert store.compare_and_swap("report.bin", "sha256:first", second, b"second") is True
    assert store.get("report.bin") == (second, b"second")


def test_filesystem_blob_store_rejects_symlinked_published_file_on_get(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    outside = tmp_path / "outside.bin"
    root.mkdir()
    outside.write_bytes(b"secret")
    try:
        os.symlink(outside, root / "report.bin")
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    store = FilesystemBlobStore(root)
    with pytest.raises(ValueError, match="symlink"):
        store.get("report.bin")


def test_filesystem_read_uses_fail_closed_final_component_open(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_bytes(b"secret")
    root = tmp_path / "blobs"
    root.mkdir()
    link = root / "blob"
    try:
        os.symlink(outside, link)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="opened safely"):
        FilesystemBlobStore._read_safe_bytes(link)
