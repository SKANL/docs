"""Sidecar process configuration (command line and environment)."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SidecarConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    workspace: Path | None = None
    health_url: str = "http://127.0.0.1:8765/health"
    protocol: str = "docs-sidecar/v1"
    # Imports are sent as JSON/base64 by the local Review Studio client. Keep
    # the transport limit above the source-import limit while retaining an
    # explicit configurable boundary instead of silently accepting unbounded
    # request bodies.
    max_body_bytes: int = 128 * 1024 * 1024
    cors_origins: tuple[str, ...] = (
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
        "http://tauri.localhost",
    )

    @classmethod
    def from_args(cls, argv: list[str]) -> SidecarConfig:
        parser = argparse.ArgumentParser(prog="docs-sidecar")
        parser.add_argument("--workspace", type=Path, default=None)
        parser.add_argument("--health-url", default=os.environ.get("DOCS_SIDECAR_HEALTH_URL", cls.health_url))
        args = parser.parse_args(argv)
        parsed = urlsplit(args.health_url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("--health-url must be an http URL bound to 127.0.0.1")
        if parsed.path != "/health" or parsed.query or parsed.fragment:
            raise ValueError("--health-url must end with the path /health")
        return cls(
            host="127.0.0.1",
            port=parsed.port or 8765,
            workspace=args.workspace or _workspace_from_environment(),
            health_url=args.health_url,
            max_body_bytes=_configured_body_limit(),
            cors_origins=tuple(
                origin.strip().rstrip("/")
                for origin in os.environ.get(
                    "DOCS_SIDECAR_CORS_ORIGINS",
                    ",".join(cls.cors_origins),
                ).split(",")
                if origin.strip()
            ),
        )



def _workspace_from_environment() -> Path | None:
    value = os.environ.get("DOCS_SIDECAR_WORKSPACE") or os.environ.get("DOCS_DOCUMENTS_DIR")
    return Path(value) if value else None


def _configured_body_limit() -> int:
    raw = os.environ.get("DOCS_MAX_BODY_BYTES", "").strip()
    if not raw:
        return SidecarConfig.max_body_bytes
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("DOCS_MAX_BODY_BYTES must be a positive integer") from exc
    if value <= 0:
        raise ValueError("DOCS_MAX_BODY_BYTES must be a positive integer")
    return value
