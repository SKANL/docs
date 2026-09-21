"""Prove that the local CLI reads the same durable records as the API layer."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from process_cleanup import terminate_process_tree


def run_cli_json(workspace: Path, *args: str) -> str:
    repo = Path(__file__).resolve().parents[2]
    json_flag = () if args[:2] == ("doc", "show") else ("--json",)
    result = subprocess.run(
        ["uv", "run", "--project", str(repo), "python", "-m", "docs.cli.main", *args, *json_flag],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def assert_same_persisted_records(
    api_document: dict[str, object],
    cli_document: dict[str, object],
    api_run: dict[str, object],
    cli_run: dict[str, object],
) -> None:
    if api_document.get("id") != cli_document.get("id"):
        raise AssertionError("document id mismatch between API and CLI")
    for key in ("title", "template", "lifecycle"):
        if key in api_document and api_document.get(key) != cli_document.get(key):
            raise AssertionError(f"document {key} mismatch between API and CLI")
    if api_run.get("id") != cli_run.get("id"):
        raise AssertionError("run id mismatch between API and CLI")
    if api_run.get("status") != cli_run.get("status"):
        raise AssertionError("run status mismatch between API and CLI")
    api_payload = api_run.get("payload") if isinstance(api_run.get("payload"), dict) else {}
    cli_payload = cli_run.get("payload") if isinstance(cli_run.get("payload"), dict) else {}
    for key in ("workspace_id", "document_id", "format"):
        if key in api_payload and api_payload.get(key) != cli_payload.get(key):
            raise AssertionError(f"run payload {key} mismatch between API and CLI")


def api_json(base: str, path: str, method: str = "GET", payload: object | None = None) -> dict[str, object]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def main() -> int:
    """Run a real packaged API -> CLI persistence journey in one workspace."""
    executable = Path(__file__).resolve().parents[1] / "sidecar" / "docs-sidecar.exe"
    if not executable.is_file():
        raise SystemExit(f"packaged sidecar not found: {executable}")
    with tempfile.TemporaryDirectory(prefix="docs-cross-surface-") as directory:
        workspace = Path(directory)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        process = subprocess.Popen(
            [os.fspath(executable), "--workspace", os.fspath(workspace), "--health-url", base + "/health"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    if api_json(base, "/health").get("ready"):
                        break
                except OSError:
                    time.sleep(0.25)
            health = api_json(base, "/health")
            if not health.get("ready"):
                raise AssertionError(f"packaged API did not become healthy: {health}")
            workspace_id = str(api_json(base, "/v1/workspaces")["items"][0]["id"])
            imported = api_json(base, "/v1/documents/import", "POST", {
                "workspace_id": workspace_id,
                "filename": "cross-surface.md",
                "content_base64": "I2Ny b3NzLXN1cmZhY2UKCkEgcmVhbCBjcm9zcy1zdXJmYWNlIGRvY3VtZW50Lg==".replace(" ", ""),
                "document_id": "cross-surface",
                "template": "documento-generico",
                "title": "Cross Surface",
            })
            if imported.get("document_id") != "cross-surface":
                raise AssertionError(f"API import failed: {imported}")
            api_json(base, "/v1/documents/cross-surface/prepare", "POST", {"workspace_id": workspace_id})
            queued = api_json(base, "/v1/runs", "POST", {"workspace_id": workspace_id, "document_id": "cross-surface", "pipeline_id": "document", "format": "docx"})
            run_id = str(queued["id"])
            current = api_json(base, "/v1/runs/" + run_id)
            deadline = time.monotonic() + 120
            while current.get("status") not in {"succeeded", "failed", "cancelled", "expired"} and time.monotonic() < deadline:
                time.sleep(0.5)
                current = api_json(base, "/v1/runs/" + run_id)
            if current.get("status") != "succeeded":
                raise AssertionError(f"API run failed: {current}")
            cli_document = json.loads(run_cli_json(workspace, "doc", "show", "cross-surface"))
            cli_runs = json.loads(run_cli_json(workspace, "run", "list"))
            cli_run = next(item for item in cli_runs if item["id"] == run_id)
            api_document = json.loads((workspace / "documents" / "cross-surface" / "document.json").read_text(encoding="utf-8"))
            assert_same_persisted_records({"id": "cross-surface", **api_document}, cli_document, current, cli_run)
            print("cross-surface packaged API -> CLI journey passed")
        finally:
            terminate_process_tree(process)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
