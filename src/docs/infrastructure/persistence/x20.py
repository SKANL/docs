from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from docs.domain.contracts import SCHEMA, Artifact, Blob, Graph, Job, Passport, Run

_JSON = dict[str, Any]


class _SqliteStore:
    def __init__(self, path: Path, *, busy_timeout_ms: int = 5_000) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        raise NotImplementedError

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        connection.execute("PRAGMA journal_mode = WAL")
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
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM x20_runs WHERE id = ?", (run_id,)).fetchone()
        return None if row is None else Run.from_dict(self._decode(row[0]))


class SqlitePassportStore(_SqliteStore):
    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS x20_passports (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

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


class SqliteArtifactStore(_SqliteStore):
    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS x20_artifacts (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL)")
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

    def list_for_run(self, run_id: str) -> list[Artifact]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM x20_artifacts WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        return [Artifact.from_dict(self._decode(row[0])) for row in rows]


class SqliteGraphStore(_SqliteStore):
    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS x20_graph (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)")

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
            connection.execute(
                "CREATE TABLE IF NOT EXISTS x20_job_cancellations ("
                "run_id TEXT PRIMARY KEY"
                ")"
            )
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
            cursor = connection.execute(
                "INSERT OR IGNORE INTO x20_job_cancellations (run_id) VALUES (?)", (run_id,)
            )
        return cursor.rowcount == 1

    def is_cancelled(self, run_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM x20_job_cancellations WHERE run_id = ?", (run_id,)
            ).fetchone()
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


class RedisJobQueue:
    def __init__(
        self,
        client: Any | None = None,
        *,
        key: str = "docs.x20.jobs",
        claim_ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self.key = key
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be positive")
        self.claim_ttl_seconds = claim_ttl_seconds
        self._clock = clock
        self.available = client is not None
        self.unavailable_reason: str | None = None

    @classmethod
    def from_url(cls, url: str, *, key: str = "docs.x20.jobs") -> RedisJobQueue:
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError as exc:
            queue = cls(None, key=key)
            queue.unavailable_reason = f"redis optional dependency unavailable: {exc}"
            return queue
        return cls(redis.Redis.from_url(url), key=key)

    @property
    def _claimed_payload_key(self) -> str:
        return f"{self.key}:claimed:payload"

    @property
    def _claimed_owner_key(self) -> str:
        return f"{self.key}:claimed:owner"

    @property
    def _claimed_expiry_key(self) -> str:
        return f"{self.key}:claimed:expiry"

    @property
    def _quarantine_key(self) -> str:
        return f"{self.key}:quarantine"

    @property
    def _cancelled_key(self) -> str:
        return f"{self.key}:cancelled"

    def enqueue(self, job_id: str, payload: dict[str, object]) -> None:
        if self._client is None:
            return
        if type(job_id) is not str or not job_id or type(payload) is not dict:
            raise TypeError("job_id must be a non-empty string and payload must be an object")
        encoded = json.dumps({"schema": SCHEMA, "id": job_id, "payload": payload}, sort_keys=True).encode("utf-8")
        self._client.rpush(self.key, encoded)

    def claim(self, worker_id: str) -> Job | None:
        if self._client is None:
            return None
        self._require_eval_capability()
        raw = self._client.eval(
            _REDIS_CLAIM_SCRIPT,
            4,
            self.key,
            self._claimed_payload_key,
            self._claimed_owner_key,
            self._claimed_expiry_key,
            worker_id,
            self._clock(),
            self.claim_ttl_seconds,
        )
        if isinstance(raw, (list, tuple)):
            response = raw
            valid, raw = response[:2]
            if not int(valid):
                return None
            job_id = response[2]
        if raw is None:
            return None
        try:
            return self._decode_job(raw)
        except (TypeError, ValueError):
            self._client.eval(
                _REDIS_QUARANTINE_SCRIPT,
                4,
                self.key,
                self._claimed_payload_key,
                self._claimed_owner_key,
                self._claimed_expiry_key,
                job_id,
                raw,
            )
            raise

    def _require_eval_capability(self) -> None:
        if not hasattr(self._client, "eval"):
            raise RuntimeError("Redis client lacks required eval capability; refusing unsafe compatibility path")

    def _reclaim_expired(self) -> None:
        client = self._client
        if client is None:
            return
        now = self._clock()
        expired = client.zrangebyscore(self._claimed_expiry_key, float("-inf"), now)
        for raw_job_id in expired:
            job_id = raw_job_id.decode("utf-8") if isinstance(raw_job_id, bytes) else raw_job_id
            payload = client.hget(self._claimed_payload_key, job_id)
            if payload is not None:
                client.rpush(self.key, payload)
            client.hdel(self._claimed_payload_key, job_id)
            client.hdel(self._claimed_owner_key, job_id)
            client.zrem(self._claimed_expiry_key, job_id)

    def ack(self, job_id: str, worker_id: str) -> bool:
        if self._client is None:
            return False
        self._require_eval_capability()
        return bool(
            self._client.eval(
                _REDIS_ACK_SCRIPT,
                3,
                self._claimed_owner_key,
                self._claimed_payload_key,
                self._claimed_expiry_key,
                job_id,
                worker_id,
            )
        )

    def cancel(self, run_id: str) -> bool:
        if self._client is None:
            return False
        sadd = getattr(self._client, "sadd", None)
        return bool(callable(sadd) and sadd(self._cancelled_key, run_id))

    def is_cancelled(self, run_id: str) -> bool:
        if self._client is None:
            return False
        sismember = getattr(self._client, "sismember", None)
        return bool(callable(sismember) and sismember(self._cancelled_key, run_id))

    @staticmethod
    def _decode_job(raw: bytes | str) -> Job:
        try:
            decoded = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("stored X20 job payload is not valid JSON") from exc
        if not isinstance(decoded, dict) or decoded.get("schema") != SCHEMA:
            raise ValueError("stored X20 job payload has an unsupported schema")
        if type(decoded.get("id")) is not str or not decoded["id"] or type(decoded.get("payload")) is not dict:
            raise ValueError("stored X20 job payload has an invalid object shape")
        return Job.from_dict(decoded)


_REDIS_CLAIM_SCRIPT = """-- x20 claim
local expired = redis.call('ZRANGEBYSCORE', KEYS[4], '-inf', ARGV[2])
for _, id in ipairs(expired) do
  local payload = redis.call('HGET', KEYS[2], id)
  if payload then redis.call('RPUSH', KEYS[1], payload) end
  redis.call('HDEL', KEYS[2], id)
  redis.call('HDEL', KEYS[3], id)
  redis.call('ZREM', KEYS[4], id)
end
local payload = redis.call('LPOP', KEYS[1])
while payload do
  local ok, decoded = pcall(cjson.decode, payload)
  if ok and type(decoded) == 'table' and decoded.schema == 'docs.x20/v1' and type(decoded.id) == 'string' and decoded.id ~= '' and type(decoded.payload) == 'table' then
    redis.call('HSET', KEYS[2], decoded.id, payload)
    redis.call('HSET', KEYS[3], decoded.id, ARGV[1])
    redis.call('ZADD', KEYS[4], tonumber(ARGV[2]) + tonumber(ARGV[3]), decoded.id)
    return {1, payload, decoded.id}
  end
  redis.call('RPUSH', KEYS[1] .. ':quarantine', payload)
  payload = redis.call('LPOP', KEYS[1])
end
return nil
"""

_REDIS_ACK_SCRIPT = """-- x20 ack
local owner = redis.call('HGET', KEYS[1], ARGV[1])
if not owner or owner ~= ARGV[2] then return 0 end
redis.call('HDEL', KEYS[1], ARGV[1])
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('ZREM', KEYS[3], ARGV[1])
return 1
"""

_REDIS_QUARANTINE_SCRIPT = """-- x20 quarantine
local job_id = ARGV[1]
local payload = ARGV[2]
redis.call('RPUSH', KEYS[1] .. ':quarantine', payload)
redis.call('HDEL', KEYS[2], job_id)
redis.call('HDEL', KEYS[3], job_id)
redis.call('ZREM', KEYS[4], job_id)
return 1
"""


SQLiteRunStore = SqliteRunStore
SQLitePassportStore = SqlitePassportStore
SQLiteArtifactStore = SqliteArtifactStore
SQLiteGraphStore = SqliteGraphStore
SQLiteJobQueue = SqliteJobQueue
SQLiteLeaseStore = SqliteLeaseStore

