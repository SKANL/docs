import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.artifacts import ArtifactRef, ArtifactState, BuildManifest


def test_record_run_writes_deterministic_hashes_and_load_run_returns_them(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    output = tmp_path / "output.docx"
    log = tmp_path / "provenance-v2.json"
    source.write_text("source body", encoding="utf-8")
    output.write_bytes(b"rendered bytes")

    record = ProvenanceLedgerV2(log).record_run("build-001", inputs=(source,), outputs=(output,))

    expected = {
        "inputs": {"source.md": hashlib.sha256(b"source body").hexdigest()},
        "outputs": {"output.docx": hashlib.sha256(b"rendered bytes").hexdigest()},
        "run_id": "build-001",
    }
    assert record == expected
    assert ProvenanceLedgerV2(log).load_run("build-001") == expected
    assert log.read_text(encoding="utf-8") == json.dumps({"runs": {"build-001": expected}, "attestations": {}}, sort_keys=True, separators=(",", ":"))


def test_record_run_appends_without_reordering_existing_runs(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    log = tmp_path / "provenance-v2.json"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    ledger = ProvenanceLedgerV2(log)

    ledger.record_run("z-run", inputs=(first,), outputs=())
    ledger.record_run("a-run", inputs=(second,), outputs=())

    assert list(json.loads(log.read_text(encoding="utf-8"))["runs"]) == ["a-run", "z-run"]


def test_verify_run_detects_changed_input_or_output(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    output = tmp_path / "output.docx"
    source.write_text("source body", encoding="utf-8")
    output.write_bytes(b"rendered bytes")
    ledger = ProvenanceLedgerV2(tmp_path / "provenance-v2.json")
    ledger.record_run("build-001", inputs=(source,), outputs=(output,))

    assert ledger.verify_run("build-001") is True
    output.write_bytes(b"changed bytes")
    assert ledger.verify_run("build-001") is False
    output.write_bytes(b"rendered bytes")
    source.write_text("changed source", encoding="utf-8")
    assert ledger.verify_run("build-001") is False


def test_record_run_replaces_log_atomically(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.md"
    log = tmp_path / "provenance-v2.json"
    source.write_text("source body", encoding="utf-8")
    ledger = ProvenanceLedgerV2(log)
    replacements: list[tuple[Path, Path]] = []

    original_replace = __import__("os").replace

    def replace(source_path: Path, destination_path: Path) -> None:
        replacements.append((source_path, destination_path))
        original_replace(source_path, destination_path)

    monkeypatch.setattr("docs.infrastructure.provenance.v2_ledger.os.replace", replace)

    ledger.record_run("build-001", inputs=(source,), outputs=())

    assert replacements[0][1] == log
    assert log.exists()
    assert not list(tmp_path.glob(".provenance-v2-*.tmp"))


def test_record_run_leaves_legacy_files_untouched(tmp_path: Path) -> None:
    legacy = tmp_path / "provenance.json"
    source = tmp_path / "source.md"
    legacy.write_text('{"legacy":true}', encoding="utf-8")
    source.write_text("source body", encoding="utf-8")

    ProvenanceLedgerV2(tmp_path / "provenance-v2.json").record_run("build-001", inputs=(source,), outputs=())

    assert legacy.read_text(encoding="utf-8") == '{"legacy":true}'

def test_verify_run_uses_paths_relative_to_the_ledger(tmp_path: Path) -> None:
    source = tmp_path / "inputs" / "source.md"
    output = tmp_path / "outputs" / "report.docx"
    source.parent.mkdir()
    output.parent.mkdir()
    source.write_text("source body", encoding="utf-8")
    output.write_bytes(b"rendered bytes")
    ledger = ProvenanceLedgerV2(tmp_path / "provenance-v2.json")

    record = ledger.record_run("build-001", inputs=(source,), outputs=(output,))

    assert set(record["inputs"]) == {"inputs/source.md"}
    assert set(record["outputs"]) == {"outputs/report.docx"}
    assert ledger.verify_run("build-001") is True


def test_record_attestation_persists_manifest_before_publication(tmp_path: Path) -> None:
    log = tmp_path / "provenance-v2.json"
    manifest = {"schema": "docs.build/v2", "document_id": "example", "artifact_hash": "a" * 64}

    record = ProvenanceLedgerV2(log).record_attestation("build-001", manifest)

    assert record == manifest
    assert ProvenanceLedgerV2(log).load_attestation("build-001") == manifest


def test_verify_attestation_requires_a_matching_verifiable_run(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")
    ledger = ProvenanceLedgerV2(tmp_path / "provenance-v2.json")
    manifest = {"schema": "docs.build/v2", "document_id": "example", "provenance_run": "build-001"}

    ledger.record_run("build-001", inputs=(source,), outputs=())
    ledger.record_attestation("build-001", manifest)

    assert ledger.verify_attestation("build-001", manifest) is True
    source.write_text("changed", encoding="utf-8")
    assert ledger.verify_attestation("build-001", manifest) is False


def test_build_manifest_attestation_is_the_persisted_verification_payload(tmp_path: Path) -> None:
    artifact = tmp_path / "output.docx"
    artifact.write_bytes(b"output")
    manifest = BuildManifest(
        document_id="example",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"renderer": "test"},
        artifacts=(ArtifactRef(str(artifact.resolve()), "".join(__import__("hashlib").sha256(b"output").hexdigest()), ArtifactState.READY),),
        verification={"passed": True},
        provenance_run="build-001",
    )
    ledger = ProvenanceLedgerV2(tmp_path / "provenance-v2.json")
    ledger.record_run("build-001", inputs=(), outputs=(artifact,))

    recorded = ledger.record_attestation("build-001", manifest.attestation())

    assert recorded == manifest.attestation()
    assert ledger.load_attestation("build-001") == manifest.attestation()
    assert ledger.verify_attestation("build-001", manifest.attestation()) is True


def test_record_run_can_verify_final_destinations_after_publication(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    destination = tmp_path / "output" / "report.docx"
    source.write_text("source", encoding="utf-8")
    destination.parent.mkdir()
    destination.write_bytes(b"published")
    ledger = ProvenanceLedgerV2(tmp_path / "runs" / "v2-provenance.json")

    ledger.record_run("build-1", inputs=(source,), outputs=(destination,))

    assert ledger.verify_run("build-1") is True
    assert ledger.load_run("build-1")["outputs"] == {
        str(destination.resolve()): hashlib.sha256(b"published").hexdigest()
    }


def test_record_run_can_attest_destination_using_prepublication_source(tmp_path: Path) -> None:
    source = tmp_path / "scratch" / "report.docx"
    destination = tmp_path / "output" / "report.docx"
    source.parent.mkdir()
    destination.parent.mkdir()
    source.write_bytes(b"published")
    ledger = ProvenanceLedgerV2(tmp_path / "runs" / "v2-provenance.json")
    ledger.record_run("build-1", inputs=(), outputs=(source,), output_identities={source: destination})
    destination.write_bytes(b"published")
    assert ledger.verify_run("build-1") is True


def test_concurrent_provenance_updates_merge_without_lost_runs(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")
    ledger = ProvenanceLedgerV2(tmp_path / "provenance-v2.json")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: ledger.record_run(f"run-{index}", inputs=(source,), outputs=()), range(8)))
    payload = json.loads((tmp_path / "provenance-v2.json").read_text(encoding="utf-8"))
    assert set(payload["runs"]) == {f"run-{index}" for index in range(8)}


def test_lock_recovers_stale_owner_metadata(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")
    log = tmp_path / "provenance-v2.json"
    lock = log.with_name(log.name + ".lock")
    lock.mkdir()
    (lock / "owner.json").write_text(json.dumps({"pid": 999999, "created_at": 0}), encoding="utf-8")
    monkeypatch.setattr("docs.infrastructure.provenance.v2_ledger.time.time", lambda: 120)

    ProvenanceLedgerV2(log).record_run("after-stale-lock", inputs=(source,), outputs=())

    assert ProvenanceLedgerV2(log).load_run("after-stale-lock") is not None


def test_lock_does_not_remove_a_stale_lock_already_claimed_by_another_recoverer(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")
    log = tmp_path / "provenance-v2.json"
    lock = log.with_name(log.name + ".lock")
    lock.mkdir()
    (lock / "owner.json").write_text(json.dumps({"pid": 999999, "created_at": 0}), encoding="utf-8")
    (lock / ".reclaim").mkdir()
    monotonic_values = iter((0, 11))
    monkeypatch.setattr("docs.infrastructure.provenance.v2_ledger.time.time", lambda: 120)
    monkeypatch.setattr(
        "docs.infrastructure.provenance.v2_ledger.time.monotonic", lambda: next(monotonic_values)
    )

    with __import__("pytest").raises(TimeoutError, match="timed out acquiring provenance lock"):
        ProvenanceLedgerV2(log).record_run("must-not-steal", inputs=(source,), outputs=())

    assert lock.exists()
    assert ProvenanceLedgerV2(log).load_run("must-not-steal") is None
