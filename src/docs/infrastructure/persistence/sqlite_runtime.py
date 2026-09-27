from __future__ import annotations

import builtins as _builtins
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from docs.domain.runtime_records import SCHEMA, Artifact, Graph, Job, Passport, Run

_JSON = dict[str, Any]


class _SqliteStore:
    def __init__(self, path: Path, *, busy_timeout_ms: int = 5_000) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Select WAL once during store construction. Repeating this PRAGMA on
        # every request can contend with a long-running worker transaction and
        # make otherwise cheap reads (run polling, progress, findings) block.
        with sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000) as connection:
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    def _initialize(self) -> None:
        raise NotImplementedError

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _encode(value: _JSON) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode(value: str) -> _JSON:
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("stored X20 payload must be a JSON object")
        if decoded.get("schema") != SCHEMA:
            raise ValueError("unsupported stored X20 payload schema")
        return decoded


class SqliteRunStore(_SqliteStore):
    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS x20_runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def put(self, run: Run) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO x20_runs (id, payload) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (run.id, self._encode(run.to_dict())),
            )

    def get(self, run_id: str) -> Run | None:
        with self._read_connection() as connection:
            row = connection.execute("SELECT payload FROM x20_runs WHERE id = ?", (run_id,)).fetchone()
        return None if row is None else Run.from_dict(self._decode(row[0]))

    def list(self) -> _builtins.list[Run]:
        with self._read_connection() as connection:
            rows = connection.execute("SELECT payload FROM x20_runs ORDER BY id").fetchall()
        return [Run.from_dict(self._decode(row[0])) for row in rows]

    def _read_connection(self) -> sqlite3.Connection:
        """Open a read-only connection that never participates in writes.

        Run polling is the hottest API read path while a worker is rendering a
        document. Keeping it independent from the writer connection prevents
        a long pipeline transaction from serializing status/progress reads.
        """
        if not self.path.exists():
            return self._connect()
        uri = f"file:{self.path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=0.5)
        connection.execute("PRAGMA query_only = ON")
        return connection


class SqlitePassportStore(_SqliteStore):
    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS x20_passports (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def put(self, passport: Passport) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO x20_passports (run_id, payload) VALUES (?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET payload = excluded.payload",
                (passport.run_id, self._encode(passport.to_dict())),
            )

    def get(self, run_id: str) -> Passport | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM x20_passports WHERE run_id = ?", (run_id,)).fetchone()
        return None if row is None else Passport.from_dict(self._decode(row[0]))


class SqliteFindingStore(_SqliteStore):
    """Durable, workspace-local findings projection for API and Review Studio."""

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS x20_findings (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS x20_findings_run_id ON x20_findings(run_id)")

    def put(self, finding: dict[str, Any]) -> None:
        envelope = {"schema": SCHEMA, "finding": dict(finding)}
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO x20_findings (id, run_id, payload) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (str(finding["id"]), str(finding.get("run_id", "")), self._encode(envelope)),
            )

    @classmethod
    def _finding(cls, value: str) -> dict[str, Any]:
        # Read old raw finding rows for compatibility, while all new rows use
        # the same versioned envelope as the other X20 projections.
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("stored finding payload must be a JSON object")
        if decoded.get("schema") == SCHEMA and isinstance(decoded.get("finding"), dict):
            return dict(decoded["finding"])
        if "id" in decoded and "run_id" in decoded:
            return decoded
        raise ValueError("unsupported stored finding payload schema")

    def list(self) -> _builtins.list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM x20_findings ORDER BY id").fetchall()
        return [self._finding(row[0]) for row in rows]

    def list_for_run(self, run_id: str) -> _builtins.list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM x20_findings WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        return [self._finding(row[0]) for row in rows]


class SqliteArtifactStore(_SqliteStore):
    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS x20_artifacts (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS x20_artifacts_run_id ON x20_artifacts (run_id)")

    def put(self, artifact: Artifact) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO x20_artifacts (id, run_id, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET run_id = excluded.run_id, payload = excluded.payload",
                (artifact.id, artifact.run_id, self._encode(artifact.to_dict())),
            )

    def get(self, artifact_id: str) -> Artifact | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM x20_artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return None if row is None else Artifact.from_dict(self._decode(row[0]))

    def list(self) -> _builtins.list[Artifact]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM x20_artifacts ORDER BY id").fetchall()
        return [Artifact.from_dict(self._decode(row[0])) for row in rows]

    def list_for_run(self, run_id: str) -> _builtins.list[Artifact]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM x20_artifacts WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        return [Artifact.from_dict(self._decode(row[0])) for row in rows]


class SqliteGraphStore(_SqliteStore):
    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS x20_graph (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)"
            )

    def put(self, graph: Graph) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO x20_graph (id, payload) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (self._encode(graph.to_dict()),),
            )

    def get(self) -> Graph:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM x20_graph WHERE id = 1").fetchone()
        return Graph() if row is None else Graph.from_dict(self._decode(row[0]))


class SqlitePublicationStore(_SqliteStore):
    """Durable publication projection exposed by the API and Review Studio."""

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS x20_publications (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def put(self, publication: dict[str, Any]) -> None:
        identifier = str(publication.get("id", ""))
        if not identifier:
            raise ValueError("publication id is required")
        envelope = {"schema": SCHEMA, "publication": dict(publication)}
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO x20_publications (id, payload) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (identifier, self._encode(envelope)),
            )

    def list(self) -> _builtins.list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM x20_publications ORDER BY id").fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            value = self._decode(row[0]).get("publication")
            if isinstance(value, dict):
                result.append(dict(value))
        return result


class SqliteJobQueue(_SqliteStore):
    def __init__(
        self,
        path: Path,
        *,
        claim_ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.time,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be positive")
        self.claim_ttl_seconds = claim_ttl_seconds
        self._clock = clock
        super().__init__(path, busy_timeout_ms=busy_timeout_ms)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS x20_jobs ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL, claimed_by TEXT, claimed_until REAL"
                ")"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS x20_jobs_quarantine ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL, reason TEXT NOT NULL"
                ")"
            )
            connection.execute("CREATE TABLE IF NOT EXISTS x20_job_cancellations (run_id TEXT PRIMARY KEY)")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(x20_jobs)")}
            if "claimed_until" not in columns:
                connection.execute("ALTER TABLE x20_jobs ADD COLUMN claimed_until REAL")
            connection.execute("CREATE INDEX IF NOT EXISTS x20_jobs_pending ON x20_jobs (claimed_by, id)")

    def enqueue(self, job_id: str, payload: dict[str, object]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO x20_jobs (id, payload, claimed_by) VALUES (?, ?, NULL)",
                (job_id, self._encode({"schema": "docs.x20/v1", "id": job_id, "payload": payload})),
            )

    def claim(self, worker_id: str) -> Job | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock()
            connection.execute(
                "UPDATE x20_jobs SET claimed_by = NULL, claimed_until = NULL "
                "WHERE claimed_by IS NOT NULL AND claimed_until <= ?",
                (now,),
            )
            row = connection.execute(
                "SELECT id, payload FROM x20_jobs WHERE claimed_by IS NULL ORDER BY rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE x20_jobs SET claimed_by = ?, claimed_until = ? WHERE id = ? AND claimed_by IS NULL",
                (worker_id, now + self.claim_ttl_seconds, row[0]),
            )
        try:
            return Job.from_dict(self._decode(row[1]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            with self._connect() as quarantine_connection:
                quarantine_connection.execute("BEGIN IMMEDIATE")
                quarantine_connection.execute(
                    "INSERT OR REPLACE INTO x20_jobs_quarantine (id, payload, reason) VALUES (?, ?, ?)",
                    (row[0], row[1], str(exc)),
                )
                quarantine_connection.execute("DELETE FROM x20_jobs WHERE id = ?", (row[0],))
            raise

    def ack(self, job_id: str, worker_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM x20_jobs WHERE id = ? AND claimed_by = ?", (job_id, worker_id))
        return cursor.rowcount == 1

    def cancel(self, run_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("INSERT OR IGNORE INTO x20_job_cancellations (run_id) VALUES (?)", (run_id,))
        return cursor.rowcount == 1

    def is_cancelled(self, run_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM x20_job_cancellations WHERE run_id = ?", (run_id,)).fetchone()
        return row is not None


class SqliteLeaseStore(_SqliteStore):
    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS x20_leases ("
                "resource TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at REAL NOT NULL"
                ")"
            )

    def acquire(self, resource: str, owner: str, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM x20_leases WHERE resource = ? AND expires_at <= ?", (resource, now))
            try:
                connection.execute(
                    "INSERT INTO x20_leases (resource, owner, expires_at) VALUES (?, ?, ?)",
                    (resource, owner, now + ttl_seconds),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def renew(self, resource: str, owner: str, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE x20_leases SET expires_at = ? WHERE resource = ? AND owner = ? AND expires_at > ?",
                (now + ttl_seconds, resource, owner, now),
            )
        return cursor.rowcount == 1

    def release(self, resource: str, owner: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM x20_leases WHERE resource = ? AND owner = ?", (resource, owner))
        return cursor.rowcount == 1


# Compatibility aliases retain the historical all-caps SQLite spelling.
SQLiteRunStore = SqliteRunStore
SQLitePassportStore = SqlitePassportStore
SQLiteArtifactStore = SqliteArtifactStore
SQLiteGraphStore = SqliteGraphStore
SQLiteJobQueue = SqliteJobQueue
SQLiteLeaseStore = SqliteLeaseStore
