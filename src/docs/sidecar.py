"""Desktop sidecar entrypoint for the local X20 API."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .api.application import X20Application
from .api.http import Response
from .api.server import GracefulHTTPServer, TransportConfig, create_server, serve

_LOG = logging.getLogger("docs.sidecar")


@dataclass(frozen=True)
class SidecarConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    workspace: Path | None = None
    health_url: str = "http://127.0.0.1:8765/health"
    protocol: str = "docs-sidecar/v1"

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
        )


class _Queue:
    def enqueue(self, run_id: str, payload: dict[str, Any]) -> None:
        del run_id, payload

    def cancel(self, run_id: str) -> None:
        del run_id


class _HealthApplication:
    def __init__(self, application: X20Application, health_path: str, protocol: str) -> None:
        self.application = application
        self.health_path = health_path
        self.protocol = protocol

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        if environ.get("PATH_INFO") == self.health_path and environ.get("REQUEST_METHOD", "GET") == "GET":
            response = Response.json({"ready": True, "protocol": self.protocol})
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(response.body))),
                    ("Connection", "close"),
                ],
            )
            return [response.body]
        return self.application(environ, start_response)


def _workspace_from_environment() -> Path | None:
    value = os.environ.get("DOCS_SIDECAR_WORKSPACE") or os.environ.get("DOCS_DOCUMENTS_DIR")
    return Path(value) if value else None


def build_application(config: SidecarConfig) -> _HealthApplication:
    application = X20Application(
        run_store={},
        queue=_Queue(),
        passport_store={},
        artifact_store={},
        graph_store={},
    )
    return _HealthApplication(application, urlsplit(config.health_url).path, config.protocol)


def build_server(config: SidecarConfig) -> GracefulHTTPServer:
    transport = TransportConfig(host=config.host, port=config.port, mode="offline", workspace=config.workspace)
    return create_server(build_application(config), transport)


def run(server: GracefulHTTPServer) -> None:
    _LOG.info(json.dumps({"event": "sidecar_started", "address": server.server_address}, default=str, sort_keys=True))
    try:
        serve(server)
    finally:
        _LOG.info(json.dumps({"event": "sidecar_stopped"}, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = SidecarConfig.from_args(argv or [])
    server = build_server(config)

    def request_shutdown(signum: int, frame: Any) -> None:
        del frame
        _LOG.info(json.dumps({"event": "sidecar_shutdown_requested", "signal": signum}, sort_keys=True))
        server.shutdown()

    previous: dict[int, Any] = {}
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            number = getattr(signal, name)
            previous[number] = signal.signal(number, request_shutdown)
    try:
        run(server)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
