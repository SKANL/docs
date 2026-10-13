"""WSGI wrapper that answers /health and degrades gracefully without an application."""

from __future__ import annotations

import multiprocessing
import threading
from collections.abc import Callable
from typing import Any

from docs.api.application import ApiApplication
from docs.api.http import Response
from docs.workers.runner import WorkerRunner


class HealthApplication:
    def __init__(
        self,
        application: ApiApplication | None,
        health_path: str,
        protocol: str,
        *,
        workspace_error: str | None = None,
        worker_runner: WorkerRunner | None = None,
        worker_thread: threading.Thread | multiprocessing.process.BaseProcess | None = None,
    ) -> None:
        self.application = application
        self.health_path = health_path
        self.protocol = protocol
        self.workspace_error = workspace_error
        self.worker_runner = worker_runner
        self.worker_thread = worker_thread

    @property
    def auth(self) -> Any:
        """Expose the composed application's validator to docs-api transport."""
        return getattr(self.application, "auth", None)

    @auth.setter
    def auth(self, validator: Any) -> None:
        if self.application is None:
            raise RuntimeError("cannot configure auth without an application")
        self.application.auth = validator

    def shutdown(self) -> None:
        if self.worker_runner is not None:
            self.worker_runner.stop()
        if self.worker_thread is not None and self.worker_thread.is_alive():
            terminate = getattr(self.worker_thread, "terminate", None)
            if callable(terminate):
                terminate()
            self.worker_thread.join(timeout=5)

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        if environ.get("PATH_INFO") == self.health_path and environ.get("REQUEST_METHOD", "GET") == "GET":
            ready = self.workspace_error is None and (self.worker_thread is None or self.worker_thread.is_alive())
            response = Response.json(
                {"ready": ready, "protocol": self.protocol}
                if ready
                else {
                    "error": self.workspace_error or "worker_not_running",
                    "protocol": self.protocol,
                    "ready": False,
                }
            )
            start_response(
                "200 OK" if ready else "503 Service Unavailable",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(response.body))),
                    ("Connection", "close"),
                ],
            )
            return [response.body]
        if self.application is None:
            response = Response.json({"error": self.workspace_error or "sidecar_unavailable"})
            start_response(
                "503 Service Unavailable",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(response.body))),
                    ("Connection", "close"),
                ],
            )
            return [response.body]
        return self.application(environ, start_response)
