"""Exercise the self-hosted API through its real HTTP transport."""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import signal
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def call(base: str, path: str, method: str = "GET", payload: object | None = None) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base + path,
        data=body,
        method=method,
        headers={"Authorization": "Bearer e2e-token", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read())
        except (OSError, ValueError):
            return error.code, {"error": str(error)}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="docs-remote-api-e2e-") as temporary:
        root = Path(temporary) / "workspace"
        config = Path(temporary) / "api.json"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config.write_text(json.dumps({"application_factory": "docs.api.production:build_application", "transport": {"host": "127.0.0.1", "port": port, "workspace": str(root)}}), encoding="utf-8")
        environment = {**os.environ, "DOCS_API_TOKENS": "e2e-token=e2e"}
        process = subprocess.Popen(["uv", "run", "docs-api", "--config", os.fspath(config)], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    if urllib.request.urlopen(base + "/health", timeout=2).status == 200:
                        break
                except OSError:
                    time.sleep(0.25)
            else:
                raise SystemExit("remote API did not become healthy")
            status, workspaces = call(base, "/v1/workspaces")
            if status != 200 or not workspaces.get("items"):
                raise SystemExit(f"workspace listing failed: {status} {workspaces}")
            workspace_id = workspaces["items"][0]["id"]
            content = base64.b64encode(b"# Remote API E2E\n\nA real remote API document.").decode()
            status, imported = call(base, "/v1/documents/import", "POST", {"workspace_id": workspace_id, "filename": "remote.md", "content_base64": content, "document_id": "remote-e2e", "template": "documento-generico", "title": "Remote API E2E"})
            if status != 201:
                raise SystemExit(f"remote import failed: {status} {imported}")
            document_id = imported["document_id"]
            status, prepared = call(base, f"/v1/documents/{document_id}/prepare", "POST", {"workspace_id": workspace_id})
            if status != 200 or prepared.get("succeeded") is False:
                raise SystemExit(f"remote prepare failed: {status} {prepared}")
            status, run = call(base, "/v1/runs", "POST", {"workspace_id": workspace_id, "document_id": document_id, "pipeline_id": "document", "format": "html"})
            if status not in {200, 201, 202}:
                raise SystemExit(f"remote run creation failed: {status} {run}")
            run_id = run["id"]
            while time.monotonic() < deadline + 120:
                status, current = call(base, f"/v1/runs/{run_id}")
                if status != 200:
                    raise SystemExit(f"remote run read failed: {status} {current}")
                if current["status"] in {"succeeded", "failed", "cancelled", "expired"}:
                    break
                time.sleep(0.5)
            if current["status"] != "succeeded":
                raise SystemExit(f"remote run failed: {current}")
            assert call(base, f"/v1/runs/{run_id}/passport")[0] == 200
            assert call(base, f"/v1/runs/{run_id}/artifacts")[1].get("items")
            graph_status, graph = call(base, f"/v1/graph?workspace_id={workspace_id}")
            if graph_status != 200 or not isinstance(graph.get("nodes"), list):
                raise SystemExit(f"remote graph read failed: {graph_status} {graph}")
            print("remote API end-to-end smoke test passed")
            return 0
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    process.send_signal(signal.SIGTERM)
                process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
