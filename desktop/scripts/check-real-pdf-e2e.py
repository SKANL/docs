"""Run the packaged sidecar against real PDF fixtures."""

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
import urllib.error
from pathlib import Path

from process_cleanup import terminate_process_tree


def call(base: str, path: str, method: str = "GET", payload: object | None = None, timeout: int = 30) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(base + path, data=body, method=method, headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read())
        except (OSError, ValueError):
            payload = {"error": str(error)}
        return error.code, payload


def main() -> int:
    fixtures = [Path(value.strip()) for value in os.environ.get("DOCS_REAL_PDF_FIXTURES", "").split(";") if value.strip()]
    if not fixtures:
        print("real PDF E2E skipped: DOCS_REAL_PDF_FIXTURES is not configured")
        return 0
    missing = [path for path in fixtures if not path.is_file() or path.suffix.lower() != ".pdf"]
    if missing:
        raise SystemExit("real PDF fixture(s) not found or not PDF: " + ", ".join(map(str, missing)))
    desktop = Path(__file__).resolve().parents[1]
    executable = Path(os.environ.get("DOCS_SIDECAR_EXECUTABLE", desktop / "sidecar" / "docs-sidecar.exe"))
    if not executable.is_file():
        raise SystemExit(f"packaged sidecar not found: {executable}")
    root = Path(tempfile.mkdtemp(prefix="docs-real-pdf-e2e-"))
    log_path = root / "sidecar.log"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{probe.getsockname()[1]}"
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen([os.fspath(executable), "--workspace", os.fspath(root / "workspace"), "--health-url", base + "/health"], stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if call(base, "/health")[1].get("ready"):
                    break
            except OSError:
                if process.poll() is not None:
                    raise SystemExit(f"packaged sidecar exited with code {process.returncode}")
                time.sleep(0.25)
        else:
            raise SystemExit("packaged sidecar did not become healthy within 60 seconds")
        workspace = call(base, "/v1/workspaces")[1]["items"][0]["id"]
        for fixture in fixtures:
            document_id = "real-" + fixture.stem.lower().replace(" ", "-")[:48]
            status, imported = call(base, "/v1/documents/import", "POST", {"workspace_id": workspace, "filename": fixture.name, "content_base64": base64.b64encode(fixture.read_bytes()).decode(), "document_id": document_id, "template": "documento-generico", "title": fixture.stem})
            if status != 201:
                raise SystemExit(f"import failed for {fixture}: {status} {imported}")
            document_id = str(imported.get("document_id") or document_id)
            status, prepared = call(base, f"/v1/documents/{document_id}/prepare", "POST", {"workspace_id": workspace}, timeout=300)
            if status != 200 or prepared.get("succeeded") is False:
                raise SystemExit(f"prepare failed for {fixture}: {status} {prepared}")
            _, run = call(base, "/v1/runs", "POST", {"workspace_id": workspace, "document_id": document_id, "pipeline_id": "document", "format": "pdf"})
            run_id = run["id"]
            timeout_seconds = int(os.environ.get("DOCS_REAL_PDF_TIMEOUT_SECONDS", "900"))
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                _, current = call(base, "/v1/runs/" + run_id)
                if current["status"] in {"succeeded", "failed", "cancelled", "expired"}:
                    break
                time.sleep(1)
            if current["status"] != "succeeded":
                raise SystemExit(f"run failed for {fixture}: {current}")
            if call(base, "/v1/runs/" + run_id + "/passport")[0] != 200:
                raise SystemExit(f"passport missing for {fixture}")
            if not call(base, "/v1/runs/" + run_id + "/artifacts")[1].get("items"):
                raise SystemExit(f"artifacts missing for {fixture}")
            print(f"real PDF E2E passed: {fixture.name} ({run_id})")
    finally:
        terminate_process_tree(process)
        log.close()
        if os.environ.get("DOCS_KEEP_REAL_PDF_E2E"):
            print(f"real PDF E2E workspace retained: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
