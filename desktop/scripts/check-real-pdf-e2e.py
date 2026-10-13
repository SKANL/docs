"""Run the packaged sidecar against real PDF fixtures."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from sidecar_harness import API, running_sidecar


def main() -> int:
    fixtures = [Path(value.strip()) for value in os.environ.get("DOCS_REAL_PDF_FIXTURES", "").split(";") if value.strip()]
    if not fixtures:
        print("real PDF E2E skipped: DOCS_REAL_PDF_FIXTURES is not configured")
        return 0
    missing = [path for path in fixtures if not path.is_file() or path.suffix.lower() != ".pdf"]
    if missing:
        raise SystemExit("real PDF fixture(s) not found or not PDF: " + ", ".join(map(str, missing)))
    timeout_seconds = int(os.environ.get("DOCS_REAL_PDF_TIMEOUT_SECONDS", "900"))
    with running_sidecar("docs-real-pdf-e2e-", health_timeout=60, log=True, keep=bool(os.environ.get("DOCS_KEEP_REAL_PDF_E2E"))) as sidecar:
        workspace = sidecar.call(f"{API}/workspaces")[1]["items"][0]["id"]
        scope = "?workspace_id=" + workspace
        for fixture in fixtures:
            document_id = "real-" + fixture.stem.lower().replace(" ", "-")[:48]
            status, imported = sidecar.call(f"{API}/documents/import", "POST", {"workspace_id": workspace, "filename": fixture.name, "content_base64": base64.b64encode(fixture.read_bytes()).decode(), "document_id": document_id, "template": "documento-generico", "title": fixture.stem})
            if status != 201:
                raise SystemExit(f"import failed for {fixture}: {status} {imported}")
            document_id = str(imported.get("document_id") or document_id)
            status, prepared = sidecar.call(f"{API}/documents/{document_id}/prepare{scope}", "POST", {"workspace_id": workspace}, timeout=300)
            if status != 200 or prepared.get("succeeded") is False:
                raise SystemExit(f"prepare failed for {fixture}: {status} {prepared}")
            _, run = sidecar.call(f"{API}/runs{scope}", "POST", {"workspace_id": workspace, "document_id": document_id, "pipeline_id": "document", "format": "pdf"})
            run_id = run["id"]
            current = sidecar.wait_run(run_id, workspace, timeout_seconds, interval=1)
            if current["status"] != "succeeded":
                raise SystemExit(f"run failed for {fixture}: {current}")
            if sidecar.call(f"{API}/runs/{run_id}/passport{scope}")[0] != 200:
                raise SystemExit(f"passport missing for {fixture}")
            if not sidecar.call(f"{API}/runs/{run_id}/artifacts{scope}")[1].get("items"):
                raise SystemExit(f"artifacts missing for {fixture}")
            print(f"real PDF E2E passed: {fixture.name} ({run_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
