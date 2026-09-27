from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from docs.domain.runtime_records import Artifact, Graph, Passport, Run
from docs.infrastructure.persistence.sqlite_runtime import (
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


def test_sqlite_adapters_enable_wal_and_busy_timeout(tmp_path: Path) -> None:
    db = tmp_path / "pragmas.sqlite3"

    store = SqliteRunStore(db, busy_timeout_ms=4321)
    with store._connect() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (4321,)


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


def test_sqlite_queue_cancellation_is_durable_and_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "queue.sqlite3"
    queue = SqliteJobQueue(db)
    queue.enqueue("job-1", {"run_id": "run-1"})

    assert queue.cancel("run-1") is True
    assert queue.cancel("run-1") is False
    assert queue.is_cancelled("run-1") is True

    reopened = SqliteJobQueue(db)
    claimed = reopened.claim("worker-1")
    assert claimed is not None and claimed.id == "job-1"


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
        assert connection.execute("SELECT payload FROM x20_jobs_quarantine WHERE id = 'bad'").fetchone() == (
            "not-json",
        )
    assert queue.claim("worker-1") is None


def test_sqlite_lease_store_rejects_non_positive_ttl(tmp_path: Path) -> None:
    leases = SqliteLeaseStore(tmp_path / "leases.sqlite3")

    with pytest.raises(ValueError, match="positive"):
        leases.acquire("run-1", "worker-1", 0)
    with pytest.raises(ValueError, match="positive"):
        leases.renew("run-1", "worker-1", -1)


def test_sqlite_lease_store_enforces_owner_and_expiry(tmp_path: Path) -> None:
    leases = SqliteLeaseStore(tmp_path / "leases.sqlite3")

    assert leases.acquire("run-1", "worker-1", 60) is True
    assert leases.acquire("run-1", "worker-2", 60) is False
    assert leases.renew("run-1", "worker-2", 60) is False
    assert leases.renew("run-1", "worker-1", 60) is True
    assert leases.release("run-1", "worker-2") is False
    assert leases.release("run-1", "worker-1") is True
