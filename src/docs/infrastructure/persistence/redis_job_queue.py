from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from docs.domain.runtime_records import SCHEMA, Job


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
