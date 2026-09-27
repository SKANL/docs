from __future__ import annotations

import json
import sys
from typing import cast

import pytest

from docs.domain.runtime_records import Job
from docs.infrastructure.persistence.redis_job_queue import _REDIS_QUARANTINE_SCRIPT, RedisJobQueue


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

    monkeypatch.setattr(
        Job, "from_dict", classmethod(lambda cls, value: (_ for _ in ()).throw(ValueError("malformed")))
    )

    with pytest.raises(ValueError, match="malformed"):
        queue.claim("worker-1")

    assert any(script.startswith("-- x20 quarantine") for script in client.scripts)


def test_redis_quarantine_script_removes_claim_without_decoding_raw_payload() -> None:
    assert "cjson.decode" not in _REDIS_QUARANTINE_SCRIPT
    assert "HGETALL" not in _REDIS_QUARANTINE_SCRIPT
    assert "ARGV[1]" in _REDIS_QUARANTINE_SCRIPT


def test_redis_quarantine_removes_only_claimed_duplicate_payload_by_id() -> None:
    payload = b'{"same":"payload"}'
    hashes = {"job-1": payload, "job-2": payload}
    quarantine: list[bytes] = []

    assert "HDEL', KEYS[2], job_id" in _REDIS_QUARANTINE_SCRIPT
    quarantine.append(payload)
    del hashes["job-2"]

    assert hashes == {"job-1": payload}
    assert quarantine == [payload]


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
            return [
                field.split(":", 1)[1]
                for field, score in self.expiry.items()
                if field.startswith(f"{key}:") and minimum <= score <= maximum
            ]

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
