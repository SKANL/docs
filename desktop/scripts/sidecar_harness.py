"""Shared harness for the packaged-sidecar checks: spawn, health-poll, call, clean up."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from process_cleanup import terminate_process_tree

DESKTOP = Path(__file__).resolve().parents[1]
API = "/v2"
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled", "expired"}


def sidecar_executable() -> Path:
    executable = Path(os.environ.get("DOCS_SIDECAR_EXECUTABLE", DESKTOP / "sidecar" / "docs-sidecar.exe"))
    if not executable.is_file():
        raise SystemExit(f"packaged sidecar not found: {executable}")
    return executable


def call(base: str, path: str, method: str = "GET", payload: object | None = None, timeout: int = 30) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(base + path, data=body, method=method, headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read())
        except (OSError, ValueError):
            return error.code, {"error": str(error)}


@dataclass
class Sidecar:
    base: str
    workspace: Path
    root: Path
    process: subprocess.Popen[bytes]
    health: dict

    def call(self, path: str, method: str = "GET", payload: object | None = None, timeout: int = 30) -> tuple[int, dict]:
        return call(self.base, path, method, payload, timeout)

    def wait_run(self, run_id: str, workspace_id: str, timeout: float, interval: float = 0.5) -> dict:
        """Poll a run until it reaches a terminal status or the deadline passes."""
        deadline = time.monotonic() + timeout
        while True:
            _, current = self.call(f"{API}/runs/{run_id}?workspace_id={workspace_id}")
            if current.get("status") in TERMINAL_RUN_STATUSES or time.monotonic() >= deadline:
                return current
            time.sleep(interval)


@contextmanager
def running_sidecar(prefix: str, *, health_timeout: float = 20, log: bool = False, keep: bool = False) -> Iterator[Sidecar]:
    """Start the packaged sidecar on a free port in a scratch workspace and stop its whole tree on exit."""
    executable = sidecar_executable()
    root = Path(tempfile.mkdtemp(prefix=prefix))
    workspace = root / "workspace"  # created by the sidecar, never pre-made
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{probe.getsockname()[1]}"
    stream = (root / "sidecar.log").open("w", encoding="utf-8") if log else None
    process = subprocess.Popen(
        [os.fspath(executable), "--workspace", os.fspath(workspace), "--health-url", base + "/health"],
        stdout=stream,
        stderr=subprocess.STDOUT if stream else None,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + health_timeout
        health: dict = {}
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SystemExit(f"packaged sidecar exited with code {process.returncode}")
            try:
                health = call(base, "/health", timeout=1)[1]
            except (OSError, ValueError):
                health = {}
            if health.get("ready"):
                break
            time.sleep(0.25)
        else:
            raise SystemExit(f"packaged sidecar did not become healthy within {health_timeout:g} seconds")
        yield Sidecar(base, workspace, root, process, health)
    finally:
        terminate_process_tree(process)
        if stream:
            stream.close()
        if keep:
            print(f"sidecar scratch workspace retained: {root}")
        else:
            # Windows releases the SQLite handle a moment after the tree is killed.
            shutil.rmtree(root, ignore_errors=True)
