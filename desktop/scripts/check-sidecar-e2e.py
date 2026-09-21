"""Exercise the packaged sidecar through import, prepare, run and passport."""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def call(base: str, path: str, method: str = "GET", payload: object | None = None) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base + path, data=body, method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status, json.loads(response.read())


def main() -> int:
    desktop = Path(__file__).resolve().parents[1]
    executable = desktop / "sidecar" / "docs-sidecar.exe"
    if not executable.is_file():
        raise SystemExit(f"packaged sidecar not found: {executable}")
    root = Path(tempfile.mkdtemp(prefix="docs-sidecar-e2e-"))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{probe.getsockname()[1]}"
    process = subprocess.Popen(
        [os.fspath(executable), "--workspace", os.fspath(root / "workspace"), "--health-url", base + "/health"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if call(base, "/health")[1].get("ready"):
                    break
            except OSError:
                time.sleep(0.25)
        _, workspaces = call(base, "/v1/workspaces")
        workspace_id = workspaces["items"][0]["id"]
        source = base64.b64encode(b"# Packaged E2E\n\nA real sidecar document.").decode()
        status, imported = call(base, "/v1/documents/import", "POST", {
            "workspace_id": workspace_id, "filename": "packaged.md",
            "content_base64": source, "document_id": "packaged-e2e",
            "template": "documento-generico", "title": "Packaged E2E",
        })
        if status != 201 or imported.get("document_id") != "packaged-e2e":
            raise SystemExit(f"import failed: {status} {imported}")
        status, prepared = call(base, "/v1/documents/packaged-e2e/prepare", "POST", {"workspace_id": workspace_id})
        if status != 200 or prepared.get("succeeded") is False:
            raise SystemExit(f"prepare failed: {status} {prepared}")
        _, run = call(base, "/v1/runs", "POST", {"workspace_id": workspace_id, "document_id": "packaged-e2e", "pipeline_id": "document", "format": "docx"})
        run_id = run["id"]
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            _, current = call(base, "/v1/runs/" + run_id)
            if current["status"] in {"succeeded", "failed", "cancelled", "expired"}:
                break
            time.sleep(0.5)
        if current["status"] != "succeeded":
            raise SystemExit(f"run failed: {current}")
        if call(base, "/v1/runs/" + run_id + "/passport")[0] != 200:
            raise SystemExit("successful run did not produce a passport")
        print("packaged sidecar end-to-end smoke test passed")
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
