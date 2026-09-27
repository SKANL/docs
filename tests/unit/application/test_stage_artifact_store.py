from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from docs.application.stage_artifact_store import StageArtifactStore
from docs.domain.pipeline_kernel import ArtifactContract
from docs.infrastructure.ingest.atomic_file_adapter import AtomicFileAdapter


def test_artifact_store_writes_a_contract_bound_record(tmp_path: Path) -> None:
    store = StageArtifactStore(tmp_path, AtomicFileAdapter())

    record = store.write(
        ArtifactContract("report", "text/plain"),
        "draft/report.txt",
        b"document body",
        metadata={"format": "txt"},
    )

    assert (tmp_path / "draft" / "report.txt").read_bytes() == b"document body"
    assert record.contract == "report"
    assert record.path == "draft/report.txt"
    assert record.sha256 == hashlib.sha256(b"document body").hexdigest()
    assert record.metadata == {"format": "txt"}


def test_artifact_store_rejects_a_symlinked_parent_that_escapes_the_root(tmp_path: Path) -> None:
    root = tmp_path / "store"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    redirected = root / "redirected"
    try:
        redirected.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    store = StageArtifactStore(root, AtomicFileAdapter())

    with pytest.raises(ValueError, match="symlink"):
        store.write(ArtifactContract("report", "text/plain"), "redirected/report.txt", b"body")

    assert not (outside / "report.txt").exists()


def test_artifact_store_rejects_a_symlinked_store_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real-store"
    real_root.mkdir()
    linked_root = tmp_path / "store"
    try:
        linked_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(ValueError, match="symlink"):
        StageArtifactStore(linked_root, AtomicFileAdapter())


def test_artifact_store_writes_deterministic_stage_receipts(tmp_path: Path) -> None:
    store = StageArtifactStore(tmp_path, AtomicFileAdapter())
    contract = ArtifactContract("resolve-config-complete")

    record = store.write_stage_receipt(contract, "resolve-config", "resolved configuration")

    assert record.contract == "resolve-config-complete"
    assert record.path == "stages/resolve-config/resolve-config-complete.json"
    assert record.producer_stage == "resolve-config"
    assert (tmp_path / record.path).read_text(encoding="utf-8") == (
        '{"detail":"resolved configuration","stage":"resolve-config"}\n'
    )
