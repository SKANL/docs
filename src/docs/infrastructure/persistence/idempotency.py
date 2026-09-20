from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docs.api.http import Response


class SqliteIdempotencyStore:
    """Durable API response replay store shared by independently restarted workers."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5_000) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS x20_idempotency ("
                "key TEXT PRIMARY KEY, expires_at REAL NOT NULL, status INTEGER NOT NULL, "
                "body BLOB NOT NULL, headers TEXT NOT NULL"
                ")"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    def get(self, key: str) -> Response | None:
        from docs.api.http import Response

        with self._connect() as connection:
            row = connection.execute(
                "SELECT expires_at, status, body, headers FROM x20_idempotency WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            if float(row[0]) <= time.time():
                connection.execute("DELETE FROM x20_idempotency WHERE key = ?", (key,))
                return None
        import json

        return Response(int(row[1]), bytes(row[2]), json.loads(row[3]))

    def put(self, key: str, response: Response, ttl: float) -> None:
        import json

        with self._connect() as connection:
            connection.execute(
                "INSERT INTO x20_idempotency (key, expires_at, status, body, headers) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET expires_at = excluded.expires_at, status = excluded.status, "
                "body = excluded.body, headers = excluded.headers",
                (
                    key,
                    time.time() + ttl,
                    response.status,
                    response.body,
                    json.dumps(dict(response.headers), sort_keys=True, separators=(",", ":")),
                ),
            )


__all__ = ["SqliteIdempotencyStore"]
