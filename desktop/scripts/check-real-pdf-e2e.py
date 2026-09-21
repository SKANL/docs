"""Process the real PDF corpus through the packaged sidecar pipeline."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
from urllib.error import HTTPError
from pathlib import Path


PDFS = (
    Path(r"C:\Users\angua\Downloads\Compilado_Anexo22_3raRMRGCE_2025 (1).pdf"),
    Path(r"C:\Users\angua\Downloads\DataStage_23082021.pdf"),
    Path(r"C:\Users\angua\Downloads\vucem009040.pdf"),
)


def call(base: str, path: str, method: str = "GET", payload: object | None = None) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base + path,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Connection": "close",
        } if body else {"Connection": "close"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def main() -> int:
    missing = [path for path in PDFS if not path.is_file()]
    if missing:
        raise SystemExit("missing corpus files: " + ", ".join(map(str, missing)))
    desktop = Path(__file__).resolve().parents[1]
    executable = desktop / "sidecar" / "docs-sidecar.exe"
    root = Path(tempfile.mkdtemp(prefix="docs-real-pdf-e2e-"))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{probe.getsockname()[1]}"
    command = [os.fspath(executable)]
    process = subprocess.Popen(
        command + ["--workspace", os.fspath(root), "--health-url", base + "/health"],
        env={**os.environ, "PYTHONPATH": os.fspath(desktop.parent / "src")},
        stdout=None,
        stderr=None,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if call(base, "/health")[1].get("ready"):
                    break
            except OSError:
                time.sleep(0.25)
        _, workspaces = call(base, "/v1/workspaces")
        workspace_id = workspaces["items"][0]["id"]
        for source in PDFS:
            document_id = "pdf-" + str(PDFS.index(source) + 1)
            print(f"[{source.name}] import", flush=True)
            query = urllib.parse.urlencode({"workspace_id": workspace_id, "document_id": document_id, "template": "documento-generico", "title": source.stem})
            request = urllib.request.Request(base + "/v1/documents/import/raw?" + query, data=source.read_bytes(), method="POST", headers={"Content-Type": "application/octet-stream", "Content-Length": str(source.stat().st_size), "X-Docs-Filename": source.name, "Connection": "close"})
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    status, imported = response.status, json.loads(response.read())
            except urllib.error.HTTPError as error:
                raise SystemExit(f"raw import failed: {error.code} {error.read().decode(errors='replace')}")
            if status != 201:
                diagnostics = process.stderr.read().decode(errors="replace") if process.stderr else ""
                raise SystemExit(f"import failed for {source.name}: {status} {imported}\n{diagnostics}")
            status, prepared = call(base, f"/v1/documents/{document_id}/prepare", "POST", {"workspace_id": workspace_id})
            print(f"[{source.name}] prepare -> {status}", flush=True)
            if status != 200 or prepared.get("succeeded") is False:
                raise SystemExit(f"prepare failed for {source.name}: {status} {prepared}")
            _, run = call(base, "/v1/runs", "POST", {
                "workspace_id": workspace_id,
                "document_id": document_id,
                "format": "html",
                "policy": "draft",
            })
            print(f"[{source.name}] run queued", flush=True)
            run_id = run["id"]
            deadline = time.monotonic() + 180
            current = None
            while time.monotonic() < deadline:
                _, current = call(base, f"/v1/runs/{run_id}")
                if current["status"] in {"succeeded", "failed", "cancelled", "expired"}:
                    break
                time.sleep(0.5)
            if current is None or current["status"] != "succeeded":
                raise SystemExit(f"run failed for {source.name}: {current}")
            _, artifacts = call(base, f"/v1/runs/{run_id}/artifacts")
            if not artifacts.get("items"):
                raise SystemExit(f"no artifacts for {source.name}")
            status, passport = call(base, f"/v1/runs/{run_id}/passport")
            if status != 200 or not passport:
                raise SystemExit(f"no evidence passport for {source.name}: {status}")
            status, findings = call(base, f"/v1/runs/{run_id}/findings")
            if status != 200 or "items" not in findings:
                raise SystemExit(f"findings were not persisted for {source.name}: {status}")
        print(f"real PDF corpus E2E passed ({len(PDFS)} files)")
        return 0
    finally:
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True)
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

