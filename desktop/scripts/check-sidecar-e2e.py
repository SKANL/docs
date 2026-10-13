"""Exercise the packaged sidecar through import, prepare, run and passport."""

from __future__ import annotations

import base64

from sidecar_harness import API, running_sidecar


def main() -> int:
    with running_sidecar("docs-sidecar-e2e-") as sidecar:
        _, workspaces = sidecar.call(f"{API}/workspaces")
        workspace_id = workspaces["items"][0]["id"]
        scope = "?workspace_id=" + workspace_id
        source = base64.b64encode(b"# Packaged E2E\n\nA real sidecar document.").decode()
        status, imported = sidecar.call(f"{API}/documents/import", "POST", {
            "workspace_id": workspace_id, "filename": "packaged.md",
            "content_base64": source, "document_id": "packaged-e2e",
            "template": "documento-generico", "title": "Packaged E2E",
        })
        if status != 201 or imported.get("document_id") != "packaged-e2e":
            raise SystemExit(f"import failed: {status} {imported}")
        status, prepared = sidecar.call(f"{API}/documents/packaged-e2e/prepare{scope}", "POST", {"workspace_id": workspace_id})
        if status != 200 or prepared.get("succeeded") is False:
            raise SystemExit(f"prepare failed: {status} {prepared}")
        _, run = sidecar.call(f"{API}/runs{scope}", "POST", {"workspace_id": workspace_id, "document_id": "packaged-e2e", "pipeline_id": "document", "format": "docx"})
        run_id = run["id"]
        current = sidecar.wait_run(run_id, workspace_id, 120)
        if current["status"] != "succeeded":
            raise SystemExit(f"run failed: {current}")
        if sidecar.call(f"{API}/runs/{run_id}/passport{scope}")[0] != 200:
            raise SystemExit("successful run did not produce a passport")
        if not sidecar.call(f"{API}/runs/{run_id}/artifacts{scope}")[1].get("items"):
            raise SystemExit("successful run did not produce artifacts")
        if "items" not in sidecar.call(f"{API}/runs/{run_id}/findings{scope}")[1]:
            raise SystemExit("successful run did not expose findings")
        print("packaged sidecar end-to-end smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
