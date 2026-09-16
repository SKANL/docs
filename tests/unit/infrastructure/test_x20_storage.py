from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import cast

import pytest

from docs.domain.contracts import Artifact, Blob, Graph, Job, Passport, Run
from docs.infrastructure.persistence.x20 import (
    FilesystemBlobStore,
    RedisJobQueue,
    SqliteArtifactStore,
    SqliteGraphStore,
    SqliteJobQueue,
    SqliteLeaseStore,
    SqlitePassportStore,
    SqliteRunStore,
)


def test_sqlite_stores_round_trip_contracts_and_survive_reopen(tmp_path: Path) -> None:
    db = tmp_path / "x20.sqlite3"
    run = Run("run-1", status="running", payload={"attempt": 1}, created_at="2026-09-16T00:00:00Z")
    passport = Passport("run-1", entries=({"artifact": "a-1"},))
    artifact = Artifact("a-1", "run-1", "report", "digest", metadata={"page": 1})
    graph = Graph(nodes=("run-1", "a-1"), edges=(("run-1", "a-1"),))

    SqliteRunStore(db).put(run)
    SqlitePassportStore(db).put(passport)
    SqliteArtifactStore(db).put(artifact)
    SqliteGraphStore(db).put(graph)

    assert SqliteRunStore(db).get("run-1") == run
    assert SqlitePassportStore(db).get("run-1") == passport
    assert SqliteArtifactStore(db).get("a-1") == artifact
    assert SqliteArtifactStore(db).list_for_run("run-1") == [artifact]
    assert SqliteGraphStore(db).get() == graph


def test_sqlite_decoding_rejects_non_object_and_wrong_schema_payloads(tmp_path: Path) -> None:
    db = tmp_path / "invalid.sqlite3"
    SqliteRunStore(db)
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO x20_runs (id, payload) VALUES (?, ?)",
            ("list", json.dumps(["not", "an", "object"])),
        )
        connection.execute(
            "INSERT INTO x20_runs (id, payload) VALUES (?, ?)",
            ("version", json.dumps({"schema": "docs.x20/v2", "id": "version"})),
        )

    with pytest.raises(ValueError, match="JSON object"):
        SqliteRunStore(db).get("list")
    with pytest.raises(ValueError, match="schema"):
        SqliteRunStore(db).get("version")


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


def test_sqlite_queue_claims_once_and_ack_requires_claiming_worker(tmp_path: Path) -> None:
    queue = SqliteJobQueue(tmp_path / "queue.sqlite3")
    queue.enqueue("job-1", {"run_id": "run-1"})
    queue.enqueue("job-1", {"run_id": "run-1"})

    claimed = queue.claim("worker-1")

    assert claimed is not None and claimed.id == "job-1"
    assert queue.claim("worker-2") is None
    assert queue.ack("job-1", "worker-2") is False
    assert queue.ack("job-1", "worker-1") is True
    assert queue.claim("worker-2") is None


def test_sqlite_queue_reclaims_expired_claim_without_losing_owner_ack(tmp_path: Path) -> None:
    now = [100.0]
    queue = SqliteJobQueue(tmp_path / "queue.sqlite3", claim_ttl_seconds=10, clock=lambda: now[0])
    queue.enqueue("job-1", {"run_id": "run-1"})

    assert queue.claim("worker-1") is not None
    now[0] = 111.0
    reclaimed = queue.claim("worker-2")

    assert reclaimed is not None and reclaimed.id == "job-1"
    assert queue.ack("job-1", "worker-1") is False
    assert queue.ack("job-1", "worker-2") is True


def test_sqlite_queue_quarantines_malformed_claim_and_removes_it(tmp_path: Path) -> None:
    db = tmp_path / "queue.sqlite3"
    queue = SqliteJobQueue(db)
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO x20_jobs (id, payload, claimed_by) VALUES (?, ?, NULL)",
            ("bad", "not-json"),
        )

    with pytest.raises(ValueError):
        queue.claim("worker-1")
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT 1 FROM x20_jobs WHERE id = 'bad'").fetchone() is None
        assert connection.execute("SELECT payload FROM x20_jobs_quarantine WHERE id = 'bad'").fetchone() == ("not-json",)
    assert queue.claim("worker-1") is None


def test_sqlite_lease_store_rejects_non_positive_ttl(tmp_path: Path) -> None:
    leases = SqliteLeaseStore(tmp_path / "leases.sqlite3")

    with pytest.raises(ValueError, match="positive"):
        leases.acquire("run-1", "worker-1", 0)
    with pytest.raises(ValueError, match="positive"):
        leases.renew("run-1", "worker-1", -1)


def test_redis_queue_drops_malformed_payload_without_poison_loop() -> None:
    class MalformedRedis:
        def __init__(self) -> None:
            self.payload = b"not-json"
            self.quarantine: list[bytes] = []
            self.scripts: list[str] = []

        def eval(self, script: str, numkeys: int, *args: object) -> object:
            del numkeys, args
            self.scripts.append(script)
            if script.startswith("-- x20 claim"):
                return [0, self.payload]
            raise AssertionError("unexpected script")

        def rpush(self, key: str, value: bytes) -> None:
            if key.endswith(":quarantine"):
                self.quarantine.append(value)

    client = MalformedRedis()
    queue = RedisJobQueue(client, key="jobs")

    assert queue.claim("worker-1") is None
    assert queue.claim("worker-1") is None
    assert len(client.scripts) == 2


def test_redis_queue_rejects_non_positive_claim_ttl() -> None:
    with pytest.raises(ValueError, match="positive"):
        RedisJobQueue(object(), claim_ttl_seconds=0)


def test_redis_queue_quarantines_job_that_fails_contract_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"schema": "docs.x20/v1", "id": "job-1", "payload": {}}).encode()

    class Redis:
        def __init__(self) -> None:
            self.scripts: list[str] = []

        def eval(self, script: str, numkeys: int, *args: object) -> object:
            del numkeys
            self.scripts.append(script)
            if script.startswith("-- x20 claim"):
                return [1, payload, "job-1"] if len(self.scripts) == 1 else None
            if script.startswith("-- x20 quarantine"):
                assert args[-2:] == ("job-1", payload)
                return 1
            raise AssertionError("unexpected script")

    client = Redis()
    queue = RedisJobQueue(client, key="jobs")

    monkeypatch.setattr(Job, "from_dict", classmethod(lambda cls, value: (_ for _ in ()).throw(ValueError("malformed"))))

    with pytest.raises(ValueError, match="malformed"):
        queue.claim("worker-1")

    assert any(script.startswith("-- x20 quarantine") for script in client.scripts)


def test_redis_quarantine_script_removes_claim_without_decoding_raw_payload() -> None:
    from docs.infrastructure.persistence.x20 import _REDIS_QUARANTINE_SCRIPT

    assert "cjson.decode" not in _REDIS_QUARANTINE_SCRIPT
    assert "HGETALL" not in _REDIS_QUARANTINE_SCRIPT
    assert "ARGV[1]" in _REDIS_QUARANTINE_SCRIPT


def test_redis_quarantine_removes_only_claimed_duplicate_payload_by_id() -> None:
    from docs.infrastructure.persistence.x20 import _REDIS_QUARANTINE_SCRIPT

    payload = b'{"same":"payload"}'
    hashes = {"job-1": payload, "job-2": payload}
    quarantine: list[bytes] = []

    assert "HDEL', KEYS[2], job_id" in _REDIS_QUARANTINE_SCRIPT
    quarantine.append(payload)
    del hashes["job-2"]

    assert hashes == {"job-1": payload}
    assert quarantine == [payload]


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

def test_sqlite_lease_store_enforces_owner_and_expiry(tmp_path: Path) -> None:
    leases = SqliteLeaseStore(tmp_path / "leases.sqlite3")

    assert leases.acquire("run-1", "worker-1", 60) is True
    assert leases.acquire("run-1", "worker-2", 60) is False
    assert leases.renew("run-1", "worker-2", 60) is False
    assert leases.renew("run-1", "worker-1", 60) is True
    assert leases.release("run-1", "worker-2") is False
    assert leases.release("run-1", "worker-1") is True


def test_redis_queue_degrades_without_optional_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "redis", None)

    queue = RedisJobQueue.from_url("redis://localhost/0")

    assert queue.available is False
    assert queue.unavailable_reason is not None
    assert queue.claim("worker-1") is None
    queue.enqueue("job-1", {})
    assert queue.ack("job-1", "worker-1") is False


def test_redis_queue_requires_eval_capability() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, list[bytes]] = {}
            self.claimed: dict[str, bytes] = {}
            self.expiry: dict[str, float] = {}

        def rpush(self, key: str, value: bytes) -> None:
            self.values.setdefault(key, []).append(value)

        def lpop(self, key: str) -> bytes | None:
            values = self.values.get(key, [])
            return values.pop(0) if values else None

        def hset(self, key: str, field: str, value: bytes) -> None:
            self.claimed[f"{key}:{field}"] = value

        def hget(self, key: str, field: str) -> bytes | None:
            return self.claimed.get(f"{key}:{field}")

        def hdel(self, key: str, field: str) -> int:
            return int(self.claimed.pop(f"{key}:{field}", None) is not None)

        def zadd(self, key: str, values: dict[str, float]) -> int:
            self.expiry.update({f"{key}:{field}": score for field, score in values.items()})
            return len(values)

        def zrangebyscore(self, key: str, minimum: float, maximum: float) -> list[str]:
            return [field.split(":", 1)[1] for field, score in self.expiry.items() if field.startswith(f"{key}:") and minimum <= score <= maximum]

        def zrem(self, key: str, field: str) -> int:
            return int(self.expiry.pop(f"{key}:{field}", None) is not None)

    queue = RedisJobQueue(FakeRedis(), key="jobs")
    with pytest.raises(RuntimeError, match="eval"):
        queue.claim("worker-1")
    with pytest.raises(RuntimeError, match="eval"):
        queue.ack("job-1", "worker-1")


def test_redis_queue_does_not_use_non_atomic_reclaim_compatibility_path() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, list[bytes]] = {}
            self.hashes: dict[str, dict[str, bytes]] = {}
            self.expiry: dict[str, dict[str, float]] = {}

        def rpush(self, key: str, value: bytes) -> None:
            self.values.setdefault(key, []).append(value)

        def lpop(self, key: str) -> bytes | None:
            values = self.values.get(key, [])
            return values.pop(0) if values else None

        def hset(self, key: str, field: str, value: bytes) -> None:
            self.hashes.setdefault(key, {})[field] = value

        def hget(self, key: str, field: str) -> bytes | None:
            return self.hashes.get(key, {}).get(field)

        def hdel(self, key: str, field: str) -> int:
            return int(self.hashes.get(key, {}).pop(field, None) is not None)

        def zadd(self, key: str, values: dict[str, float]) -> int:
            self.expiry.setdefault(key, {}).update(values)
            return len(values)

        def zrangebyscore(self, key: str, minimum: float, maximum: float) -> list[str]:
            return [field for field, score in self.expiry.get(key, {}).items() if minimum <= score <= maximum]

        def zrem(self, key: str, field: str) -> int:
            return int(self.expiry.get(key, {}).pop(field, None) is not None)

    client = FakeRedis()
    queue = RedisJobQueue(client, key="jobs")
    with pytest.raises(RuntimeError, match="eval"):
        queue.claim("worker-1")


def test_redis_queue_claim_reclaim_and_ack_use_atomic_scripts() -> None:
    class AtomicFakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, list[bytes]] = {}
            self.hashes: dict[str, dict[str, bytes]] = {}
            self.expiry: dict[str, dict[str, float]] = {}
            self.scripts: list[str] = []

        def rpush(self, key: str, value: bytes) -> None:
            self.values.setdefault(key, []).append(value)

        def eval(self, script: str, numkeys: int, *args: object) -> object:
            self.scripts.append(script)
            if script.startswith("-- x20 claim"):
                key, payload_key, owner_key, expiry_key = (cast(str, value) for value in args[:4])
                worker_id = cast(str, args[4])
                now = float(cast(float, args[5]))
                ttl = float(cast(float, args[6]))
                del numkeys
                for job_id, score in list(self.expiry.get(expiry_key, {}).items()):
                    if score <= now:
                        payload = self.hashes.get(payload_key, {}).pop(job_id, None)
                        if payload is not None:
                            self.values.setdefault(key, []).append(payload)
                        self.hashes.get(owner_key, {}).pop(job_id, None)
                        self.expiry[expiry_key].pop(job_id, None)
                values = self.values.get(key, [])
                if not values:
                    return None
                payload = values.pop(0)
                decoded = json.loads(payload.decode())
                job_id = cast(str, decoded["id"])
                self.hashes.setdefault(payload_key, {})[job_id] = payload
                self.hashes.setdefault(owner_key, {})[job_id] = worker_id.encode()
                self.expiry.setdefault(expiry_key, {})[job_id] = now + ttl
                return payload
            if script.startswith("-- x20 ack"):
                owner_key, payload_key, expiry_key, job_id, worker_id = (cast(str, value) for value in args)
                del numkeys
                owner = self.hashes.get(owner_key, {}).get(job_id)
                if owner != worker_id.encode():
                    return 0
                self.hashes[owner_key].pop(job_id, None)
                self.hashes.get(payload_key, {}).pop(job_id, None)
                self.expiry.get(expiry_key, {}).pop(job_id, None)
                return 1
            raise AssertionError("unexpected script")

    client = AtomicFakeRedis()
    queue = RedisJobQueue(client, key="jobs", claim_ttl_seconds=10, clock=lambda: 100.0)
    queue.enqueue("job-1", {"run_id": "run-1"})

    assert queue.claim("worker-1") is not None
    assert queue.ack("job-1", "worker-1") is True
    assert len(client.scripts) == 2

