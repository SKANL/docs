"""Smoke-test the packaged Windows sidecar against a fresh workspace."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def main() -> int:
    desktop = Path(__file__).resolve().parents[1]
    executable = desktop / "sidecar" / "docs-sidecar.exe"
    if not executable.is_file():
        raise SystemExit(f"packaged sidecar not found: {executable}")
    workspace = Path(tempfile.mkdtemp(prefix="docs-sidecar-runtime-"))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    health_url = f"http://127.0.0.1:{port}/health"
    process = subprocess.Popen(
        [os.fspath(executable), "--workspace", os.fspath(workspace), "--health-url", health_url],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 20
        response = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SystemExit(f"packaged sidecar exited with code {process.returncode}")
            try:
                with urllib.request.urlopen(health_url, timeout=1) as stream:
                    response = json.loads(stream.read().decode("utf-8"))
                break
            except (OSError, json.JSONDecodeError):
                time.sleep(0.25)
        if response != {"protocol": "docs-sidecar/v1", "ready": True}:
            raise SystemExit(f"unexpected sidecar health response: {response!r}")
        template = workspace / "templates" / "documento-generico.json"
        if not template.is_file():
            raise SystemExit("fresh packaged sidecar did not seed built-in templates")
        print("packaged sidecar runtime smoke test passed")
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
