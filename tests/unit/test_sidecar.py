from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, ClassVar

import pytest

from docs.api.http import Request
from docs.domain.runtime_records import Artifact, Run
from docs.domain.workspace import Workspace
from docs.sidecar import SidecarConfig, build_application, build_server, run
from docs.sidecar.worker import build_worker, persist_worker_evidence


@pytest.fixture(autouse=True)
def _canonical_workspace_root(canonical_workspace_root: Path) -> None:
    """Opt this module into canonical temporary workspaces."""


def test_api_document_creation_composes_the_requested_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from docs.api.http import Request
    from docs.composition import open_workspace_registry
    from docs.domain.models.document import DocumentSummary

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    registry_path = tmp_path / ".docs" / "workspaces.json"
    registry = open_workspace_registry(registry_path)
    first = registry.create("First", first_root)
    second = registry.create("Second", second_root)
    registry.select(first["id"])
    calls: list[Workspace] = []

    class Documents:
        def __init__(self) -> None:
            self.items: list[DocumentSummary] = []
            self.active_id = ""

        def create(self, document_id: str, template: str, title: str) -> None:
            self.items.append(DocumentSummary(
                id=document_id,
                title=title,
                template=template,
                created_at="2026-01-01T00:00:00",
            ))
            self.active_id = document_id

        def list(self) -> list[DocumentSummary]:
            return self.items

        def current(self) -> str:
            return self.active_id

    class Composition:
        documents = Documents()

    def compose(workspace: Workspace) -> Composition:
        calls.append(workspace)
        return Composition()

    monkeypatch.setattr("docs.sidecar.document_actions.compose_application", compose)
    application = build_application(SidecarConfig(workspace=tmp_path))
    try:
        response = application.application.dispatch(Request(
            "POST",
            "/v2/documents",
            body=json.dumps({"workspace_id": second["id"], "document_id": "target", "template": "documento-generico", "title": "Target"}).encode(),
            headers={"Content-Type": "application/json"},
        ))
        assert response.status == 201
        assert calls == [Workspace(second_root / "documents", second_root / "templates")]
        assert registry.active()["id"] == first["id"]
    finally:
        application.shutdown()


def test_api_context_reads_compose_each_requested_workspace_without_leakage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from docs.api.http import Request
    from docs.composition import open_workspace_registry

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    registry_path = tmp_path / ".docs" / "workspaces.json"
    registry = open_workspace_registry(registry_path)
    first = registry.create("First", first_root)
    second = registry.create("Second", second_root)
    registry.select(first["id"])
    calls: list[Path] = []

    class Context:
        def status(self, document_id: str, template: Any) -> list[Any]:
            return []

    class Composition:
        context = Context()

        def __init__(self, workspace: Workspace) -> None:
            self.workspace = workspace

        def resolve_context(self, document_id: str) -> Any:
            calls.append(self.workspace.documents_dir)
            return type("Resolved", (), {"template": type("Template", (), {"context_schema": type("Schema", (), {"topics": []})()})()})()

    def compose(workspace: Workspace) -> Composition:
        return Composition(workspace)

    monkeypatch.setattr("docs.sidecar.document_actions.compose_application", compose)
    application = build_application(SidecarConfig(workspace=tmp_path))
    try:
        for workspace in (first, second):
            (Path(str(workspace["root"])) / "documents" / "doc").mkdir(parents=True, exist_ok=True)
            (Path(str(workspace["root"])) / "documents" / "doc" / "document.json").write_text(
                json.dumps({"id": "doc", "title": "Doc"}), encoding="utf-8"
            )
            response = application.application.dispatch(Request(
                "GET",
                f"/v2/documents/doc/context?workspace_id={workspace['id']}",
            ))
            assert response.status == 200
            assert json.loads(response.body)["document_id"] == "doc"
        assert calls == [first_root / "documents", second_root / "documents"]
        assert registry.active()["id"] == first["id"]
    finally:
        application.shutdown()


def test_sidecar_worker_bootstrap_reuses_the_shared_application_composition(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observability = object()
    calls = []
    application = type("Application", (), {"observability": observability})()

    monkeypatch.setattr("docs.sidecar.worker.compose_application", lambda workspace: calls.append(workspace) or application)

    runner = build_worker(
        tmp_path,
        object(),
        object(),
        object(),
        object(),
        object(),
        object(),
        object(),
    )

    assert calls == [Workspace(tmp_path / "documents", tmp_path / "templates")]
    assert runner._service.observability is observability


def test_sidecar_defaults_are_loopback_and_protocol_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCS_SIDECAR_WORKSPACE", raising=False)
    monkeypatch.delenv("DOCS_DOCUMENTS_DIR", raising=False)
    config = SidecarConfig.from_args([])
    assert config.host == "127.0.0.1"
    assert config.port == 8765
    assert config.protocol == "docs-sidecar/v1"
    assert "http://localhost:1420" in config.cors_origins


def test_worker_passport_contains_each_pipeline_stage_receipt() -> None:
    class Store:
        def __init__(self) -> None:
            self.value = None

        def put(self, value) -> None:
            self.value = value

    class Result:
        run_id = "run-1"
        state = "succeeded"
        attempt = 1
        retry_of = "run-original"
        worker_id = "worker-test"
        value: ClassVar[dict[str, object]] = {"report": {"execution": {"results": [
            {"stage": "render", "ok": True, "outcome": "succeeded"},
            {"stage": "verify", "ok": True, "outcome": "succeeded"},
        ]}}}

    passports, artifacts, findings = Store(), Store(), Store()
    persist_worker_evidence(passports, artifacts, findings, Result())

    assert [entry["stage"] for entry in passports.value.entries] == [
        "worker", "pipeline", "pipeline_stage", "pipeline_stage"
    ]
    assert [entry["stage"] for entry in passports.value.entries[2:]] == ["pipeline_stage", "pipeline_stage"]
    assert [entry["name"] for entry in passports.value.entries[2:]] == ["render", "verify"]
    assert [entry["receipt"]["outcome"] for entry in passports.value.entries[2:]] == ["succeeded", "succeeded"]
    assert passports.value.entries[0]["retry_of"] == "run-original"
    assert passports.value.entries[0]["worker_id"] == "worker-test"


def test_sidecar_accepts_workspace_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCS_SIDECAR_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("DOCS_DOCUMENTS_DIR", raising=False)

    assert SidecarConfig.from_args([]).workspace == tmp_path


def test_sidecar_uses_a_configurable_import_body_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCS_MAX_BODY_BYTES", "4194304")
    assert SidecarConfig.from_args([]).max_body_bytes == 4194304


def test_sidecar_rejects_invalid_import_body_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCS_MAX_BODY_BYTES", "not-a-number")
    with pytest.raises(ValueError, match="DOCS_MAX_BODY_BYTES"):
        SidecarConfig.from_args([])


def test_sidecar_allows_review_studio_origin(tmp_path: Path) -> None:
    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    server = build_server(config)
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v2/openapi.json",
            headers={"Origin": "http://localhost:1420"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 200
            assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:1420"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_sidecar_health_is_real_http_and_shutdown_is_graceful(tmp_path: Path) -> None:
    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    server = build_server(config)
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/health"
        with urllib.request.urlopen(url, timeout=2) as response:
            assert response.status == 200
            assert json.load(response) == {"protocol": "docs-sidecar/v1", "ready": True}
    finally:
        server.shutdown()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_sidecar_reports_workspace_not_configured_without_workspace() -> None:
    config = SidecarConfig(host="127.0.0.1", port=0, workspace=None)
    server = build_server(config)
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/health"
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url, timeout=2)
        with error.value as response:
            assert response.status == 503
            assert json.load(response) == {
                "error": "workspace_not_configured",
                "protocol": "docs-sidecar/v1",
                "ready": False,
            }
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_sidecar_runs_endpoint_reads_workspace_backed_store(tmp_path: Path) -> None:
    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    server = build_server(config)
    workspace_id = server._docs_application.application.workspace_registry.list()[0]["id"]
    server._docs_application.application.run_store.put(Run("run-1", payload={"workspace_id": workspace_id}, created_at="2026-01-01T00:00:00+00:00"))
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v2/runs?workspace_id={workspace_id}"
        with urllib.request.urlopen(url, timeout=2) as response:
            assert response.status == 200
            assert json.load(response)["items"][0]["id"] == "run-1"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_sidecar_wsgi_routes_document_use_with_workspace_query(tmp_path: Path) -> None:
    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    server = build_server(config)
    application = server._docs_application.application
    workspace_id = application.workspace_registry.list()[0]["id"]
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()

    def post(path: str, payload: dict[str, str]) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=30)  # hang guard; first request composes the workspace services
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    try:
        status, created = post(
            "/v2/documents",
            {
                "workspace_id": workspace_id,
                "document_id": "wsgi-lifecycle",
                "template": "documento-generico",
                "title": "WSGI lifecycle",
            },
        )
        assert status == 201

        status, selected = post(
            f"/v2/documents/{created['id']}/use?workspace_id={workspace_id}",
            {},
        )

        assert status == 200, selected
        assert selected["id"] == "wsgi-lifecycle"
        assert selected["active"] is True
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_sidecar_wsgi_authoring_routes_use_real_composition(tmp_path: Path) -> None:
    import base64

    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    server = build_server(config)
    application = server._docs_application.application
    workspace_id = application.workspace_registry.list()[0]["id"]
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()

    def call(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    scope = f"workspace_id={workspace_id}"
    try:
        status, _ = call("POST", "/v2/documents", {
            "workspace_id": workspace_id, "document_id": "authoring", "template": "documento-generico", "title": "A",
        })
        assert status == 201

        status, added = call("POST", f"/v2/documents/authoring/assets?{scope}", {
            "filename": "cover.docx", "content_base64": base64.b64encode(b"PKcover").decode(),
        })
        assert status == 201, added
        status, listed = call("GET", f"/v2/documents/authoring/assets?{scope}")
        assert listed["items"] == [{"name": "cover"}]

        status, ingested = call("POST", f"/v2/documents/authoring/ingest?{scope}", {"files": [
            {"filename": "n.md", "content_base64": base64.b64encode(b"# Hola\n\nTexto.\n").decode()},
        ]})
        assert status == 200, ingested
        assert ingested["stages"][0]["name"] == "ingest-sources"

        status, queue = call("GET", f"/v2/documents/authoring/classification?{scope}")
        assert status in {200, 404}, queue

        status, elicited = call("POST", f"/v2/documents/authoring/context/requests?{scope}", {"topic": "tema"})
        assert status == 200, elicited
        status, _missing = call("GET", f"/v2/documents/ghost/assets?{scope}")
        assert status == 404
        status, removed = call("DELETE", f"/v2/documents/authoring/assets/cover?{scope}")
        assert status == 200 and removed["removed"] == "cover"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_sidecar_wsgi_section_routes_use_real_composition(tmp_path: Path) -> None:
    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    server = build_server(config)
    workspace_id = server._docs_application.application.workspace_registry.list()[0]["id"]
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()

    def call(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    scope = f"workspace_id={workspace_id}"
    base = "/v2/documents/sections"
    try:
        status, _ = call("POST", "/v2/documents", {
            "workspace_id": workspace_id, "document_id": "sections", "template": "documento-generico", "title": "S",
        })
        assert status == 201
        status, built = call("POST", f"{base}/sections/introduccion/build?{scope}", {})
        assert status == 200 and built["proposal"] is False, built
        status, reviewed = call("POST", f"{base}/sections/introduccion/review?{scope}", {"strict": True})
        assert status == 200 and reviewed["findings"], reviewed
        status, stamped = call("POST", f"{base}/sections/introduccion/stamp?{scope}", {"by": "ada", "model": "m"})
        assert status == 200 and stamped["authored_by"] == "ada", stamped
        status, revised = call("POST", f"{base}/revisions?{scope}", {"target_id": "introduccion", "new_body": "Nuevo.\n"})
        assert status == 201 and revised["diff_path"].startswith("sections/_revisions/"), revised
        status, missing = call("POST", f"/v2/documents/ghost/sections/introduccion/build?{scope}", {})
        assert status == 404, missing
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_sidecar_wsgi_delivery_routes_package_and_publish_a_verified_build(tmp_path: Path) -> None:
    import hashlib

    from docs.application.document_pipeline import _current_input_identities, _resolve_publish_inputs
    from docs.domain.artifacts import ArtifactRef, BuildManifest
    from docs.infrastructure.provenance.ledger import ProvenanceLedger

    server = build_server(SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path))
    application = server._docs_application.application
    workspace = application.workspace_registry.list()[0]
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()

    def call(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    scope = f"workspace_id={workspace['id']}"
    try:
        status, _ = call("POST", "/v2/documents", {
            "workspace_id": workspace["id"], "document_id": "ship", "template": "documento-generico", "title": "S",
        })
        assert status == 201
        status, missing = call("POST", f"/v2/documents/ship/package?{scope}", {})
        assert status == 409 and missing["error"]["code"] == "package_source_unavailable", missing

        # a real verified build: live identities + a recorded attestation (what a pipeline run leaves behind)
        root = Path(workspace["root"]).resolve() / "documents" / "ship"
        deps = application._workspace_services_for(str(Path(workspace["root"]).resolve()))
        resolved, config, renderer = _resolve_publish_inputs(deps, root, "docx")
        ids = _current_input_identities(resolved=resolved, config=config, renderer=renderer, root=root, output_format="docx")
        current = root / "output" / "current"
        current.mkdir(parents=True, exist_ok=True)
        artifact = current / "ship.docx"
        artifact.write_bytes(b"docx-bytes")
        manifest = BuildManifest(
            document_id="ship", source_hash=ids["source_hash"], template_hash=ids["template_hash"],
            template_ir_hash=ids["template_ir_hash"], config_hash=ids["config_hash"], context_hash=ids["context_hash"],
            asset_hashes=ids["asset_hashes"], renderer_versions=ids["renderer_versions"],
            artifacts=(ArtifactRef(str(artifact.resolve()), hashlib.sha256(artifact.read_bytes()).hexdigest()),),
            verification={"passed": True}, provenance_run="run-1",
        )
        (current / "ship.docx.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
        (root / "runs").mkdir(exist_ok=True)
        ledger = ProvenanceLedger(root / "runs" / "provenance.json", trusted_root=root)
        ledger.record_run("run-1", inputs=(), outputs=())
        ledger.record_attestation("run-1", manifest.attestation())
        # the sidecar projects publications through the pipeline run that built the artifact
        application.run_store.put(Run("run-1", "succeeded", {"workspace_id": workspace["id"], "document_id": "ship"}, ""))

        status, packaged = call("POST", f"/v2/documents/ship/package?{scope}", {"name": "v1"})
        assert status == 200, packaged
        assert packaged["destination"] == "artifacts/packages/ship-v1.zip"
        status, again = call("POST", f"/v2/documents/ship/package?{scope}", {"name": "v1"})
        assert status == 200 and again["sha256"] == packaged["sha256"]

        status, denied = call("POST", f"/v2/documents/ship/publications?{scope}", {"destination": "a.docx", "policy": "draft"})
        assert status == 422 and denied["error"]["code"] == "publish_policy_denied", denied
        status, escaped = call("POST", f"/v2/documents/ship/publications?{scope}", {"destination": "../a.docx"})
        assert status == 400 and escaped["error"]["code"] == "destination_not_permitted", escaped
        status, published = call("POST", f"/v2/documents/ship/publications?{scope}", {"destination": "a.docx"})
        assert status == 201, published
        assert published["artifact_sha256"] == hashlib.sha256(b"docx-bytes").hexdigest()
        assert (root / "output" / "release" / "a.docx").read_bytes() == b"docx-bytes"
        status, listed = call("GET", f"/v2/publications?{scope}")
        assert [item["id"] for item in listed["items"]] == [published["id"]], listed
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_sidecar_wsgi_template_and_summary_routes_use_real_composition(tmp_path: Path) -> None:
    server = build_server(SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path))
    application = server._docs_application.application
    workspace = application.workspace_registry.list()[0]
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()

    def call(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    scope = f"workspace_id={workspace['id']}"
    try:
        status, shown = call("GET", f"/v2/templates/documento-generico?{scope}")
        assert status == 200 and shown["template"]["type"], shown
        status, missing = call("GET", f"/v2/templates/nope?{scope}")
        assert status == 404 and missing["error"]["code"] == "template_not_found", missing
        status, created = call("POST", f"/v2/templates?{scope}", {"name": "borrador"})
        assert status == 201 and created["path"] == "templates/borrador.json", created
        status, again = call("POST", f"/v2/templates?{scope}", {"name": "borrador"})
        assert status == 409 and again["error"]["code"] == "template_exists", again
        status, refused = call("POST", f"/v2/templates/documento-generico/use?{scope}", {})
        assert status == 409 and refused["error"]["code"] == "template_exists", refused
        status, forced = call("POST", f"/v2/templates/documento-generico/use?{scope}", {"force": True})
        assert status == 200, forced
        status, checked = call("POST", f"/v2/templates/borrador/validate?{scope}", {})
        assert status == 200 and checked["passed"] is False and checked["issues"], checked
        status, escaped = call("POST", f"/v2/templates?{scope}", {"name": "../x"})
        assert status == 400, escaped
        status, _ = call("POST", "/v2/documents", {
            "workspace_id": workspace["id"], "document_id": "sumario", "template": "documento-generico", "title": "S",
        })
        assert status == 201
        status, summary = call("GET", f"/v2/documents/sumario/summary?{scope}")
        assert status == 200 and summary["summary"]["doc_id"] == "sumario", summary
        status, imported = call("POST", f"/v2/documents/sumario/imports?{scope}", {"filename": "n.md", "content_base64": "aGk="})
        assert status == 201 and imported["path"].startswith("documents/sumario/inbox/"), imported
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_sidecar_templates_endpoint_reads_workspace_manifests(tmp_path: Path) -> None:
    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    health_app = build_application(config)
    try:
        workspace_id = health_app.application.workspace_registry.list()[0]["id"]
        response = health_app.application.dispatch(Request("GET", f"/v2/templates?workspace_id={workspace_id}"))
        payload = json.loads(response.body)
        ids = {item["id"] for item in payload["items"]}
        assert response.status == 200
        assert {"documento-generico", "technical-report-srs", "reporte-estadia-tic"} <= ids
    finally:
        health_app.shutdown()


def test_sidecar_lists_a_real_workspace_baseline(tmp_path: Path) -> None:
    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    health_app = build_application(config)
    try:
        baseline_dir = tmp_path / "baselines"
        baseline_dir.mkdir(exist_ok=True)
        baseline = baseline_dir / "desktop.json"
        baseline.write_text(json.dumps({"id": "desktop", "scope": "html"}), encoding="utf-8")
        workspaces = json.loads(health_app.application.dispatch(Request("GET", "/v2/workspaces")).body)
        workspace_id = workspaces["items"][0]["id"]
        response = health_app.application.dispatch(Request("GET", f"/v2/baselines?workspace_id={workspace_id}"))
        assert response.status == 200
        assert any(item["id"] == "desktop" for item in json.loads(response.body)["items"])
    finally:
        health_app.shutdown()


def test_sidecar_composes_all_sqlite_stores_in_workspace(tmp_path: Path) -> None:
    application = build_application(SidecarConfig(workspace=tmp_path))

    assert application.application.run_store.path == tmp_path / ".docs" / "runtime.sqlite3"
    assert application.application.queue.path == tmp_path / ".docs" / "runtime.sqlite3"
    assert application.application.passport_store.path == tmp_path / ".docs" / "runtime.sqlite3"
    assert application.application.artifact_store.path == tmp_path / ".docs" / "runtime.sqlite3"
    assert application.application.graph_store.path == tmp_path / ".docs" / "runtime.sqlite3"


def test_sidecar_empty_graph_is_an_empty_graph(tmp_path: Path) -> None:
    from docs.composition import open_workspace_registry

    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    server = build_server(config)
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()
    try:
        workspace_id = open_workspace_registry(tmp_path / ".docs" / "workspaces.json").list()[0]["id"]
        url = f"http://127.0.0.1:{server.server_address[1]}/v2/graph?workspace_id={workspace_id}"
        with urllib.request.urlopen(url, timeout=2) as response:
            assert json.load(response) == {"nodes": [], "edges": []}
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_filesystem_stores_follow_the_selected_workspace_and_ignore_invalid_manifests(tmp_path: Path) -> None:
    """The sidecar reads each canonical workspace boundary, never process cwd state."""
    from docs.composition import open_workspace_registry
    from docs.sidecar.stores import FilesystemDocumentStore, FilesystemTemplateStore

    registry = open_workspace_registry(tmp_path / ".docs" / "workspaces.json")
    first_root, second_root = tmp_path / "first", tmp_path / "second"
    registry.create("First", first_root)
    second = registry.create("Second", second_root)
    registry.select(second["id"])
    (first_root / "documents" / "first").mkdir(parents=True)
    (first_root / "documents" / "first" / "document.json").write_text('{"title":"First"}', encoding="utf-8")
    (second_root / "documents" / "second").mkdir(parents=True)
    (second_root / "documents" / "second" / "document.json").write_text('{"title":"Second"}', encoding="utf-8")
    (second_root / "documents" / "broken").mkdir(parents=True)
    (second_root / "documents" / "broken" / "document.json").write_text("not json", encoding="utf-8")
    (first_root / "templates").mkdir(parents=True, exist_ok=True)
    (second_root / "templates").mkdir(parents=True, exist_ok=True)
    (second_root / "templates" / "template.json").write_text('{"template_version":"2"}', encoding="utf-8")
    (second_root / "templates" / "bad.json").write_text("[", encoding="utf-8")

    documents = FilesystemDocumentStore(tmp_path, registry)
    templates = FilesystemTemplateStore(tmp_path, registry)

    assert documents.list() == [{"title": "Second", "id": "second"}]
    assert documents.get("second") == {"title": "Second", "id": "second"}
    assert documents.get("missing") is None
    assert documents.list_for_workspace(first_root) == [{"title": "First", "id": "first"}]
    template = next(item for item in templates.list_for_workspace(second["id"]) if item["id"] == "template")
    assert template["id"] == "template"
    assert template["version"] == "2"
    assert template["source_path"].endswith("template.json")


def test_workspace_json_collection_reads_revision_lists_and_promotes_only_real_baselines(tmp_path: Path) -> None:
    from docs.composition import open_workspace_registry
    from docs.sidecar.stores import WorkspaceJsonCollectionStore

    registry = open_workspace_registry(tmp_path / ".docs" / "workspaces.json")
    workspace = registry.create("Workspace", tmp_path / "workspace")
    registry.select(workspace["id"])
    root = Path(workspace["root"])
    baselines = root / "baselines"
    baselines.mkdir(exist_ok=True)
    (baselines / "baseline.json").write_text('{"id":"baseline","status":"passed"}', encoding="utf-8")
    (baselines / "active.json").write_text('{"id":"old"}', encoding="utf-8")
    revisions = root / "documents" / "doc" / "sections" / "_revisions"
    revisions.mkdir(parents=True)
    (revisions / "revision-log.json").write_text('[{"id":"revision-1"}]', encoding="utf-8")

    baseline_store = WorkspaceJsonCollectionStore(tmp_path, "baselines", registry)
    revision_store = WorkspaceJsonCollectionStore(tmp_path, "revisions", registry)

    assert [item["id"] for item in baseline_store.list()] == ["baseline"]
    assert [item["id"] for item in revision_store.list()] == ["revision-1"]
    assert baseline_store.promote("missing") is None
    promoted = baseline_store.promote_for_workspace(workspace["id"], "baseline", {"actor": "test"})
    assert promoted is not None
    assert {key: promoted[key] for key in ("id", "status", "promoted", "promotion")} == {
        "id": "baseline", "status": "passed", "promoted": True, "promotion": {"actor": "test"}
    }
    assert json.loads((baselines / "active.json").read_text(encoding="utf-8")) == promoted
    assert revision_store.promote("revision-1") is None


def test_revision_store_lists_each_entry_of_the_real_revision_log(tmp_path: Path) -> None:
    from docs.composition import open_workspace_registry
    from docs.sidecar.stores import WorkspaceJsonCollectionStore

    registry = open_workspace_registry(tmp_path / ".docs" / "workspaces.json")
    workspace = registry.create("Workspace", tmp_path / "workspace")
    registry.select(workspace["id"])
    revisions = Path(workspace["root"]) / "documents" / "doc" / "sections" / "_revisions"
    revisions.mkdir(parents=True)
    log = {"schema": 1, "entries": [{"section_id": "a", "ts": "t1"}, {"section_id": "b", "ts": "t2"}]}
    (revisions / "revision-log.json").write_text(json.dumps(log), encoding="utf-8")

    items = WorkspaceJsonCollectionStore(tmp_path, "revisions", registry).list()

    assert [item["section_id"] for item in items] == ["a", "b"]


def test_workspace_backed_stores_reject_noncanonical_roots(tmp_path: Path) -> None:
    from docs.application.workspaces import WorkspaceRegistryError
    from docs.composition import open_workspace_registry
    from docs.sidecar.stores import WorkspaceRunStore

    registry = open_workspace_registry(tmp_path / ".docs" / "workspaces.json")
    workspace = registry.create("Workspace", tmp_path / "workspace")
    (Path(workspace["root"]) / "workspace.json").unlink()

    with pytest.raises(WorkspaceRegistryError, match="workspace_marker_missing"):
        WorkspaceRunStore(registry).put(Run("run", payload={"workspace_id": workspace["id"]}))


def test_workspace_runtime_and_evidence_stores_keep_records_in_the_run_workspace(tmp_path: Path) -> None:
    from docs.composition import open_workspace_registry
    from docs.sidecar.stores import WorkspaceEvidenceStores, WorkspaceJobQueue, WorkspaceRunStore

    registry = open_workspace_registry(tmp_path / ".docs" / "workspaces.json")
    first = registry.create("First", tmp_path / "first")
    second = registry.create("Second", tmp_path / "second")
    runs = WorkspaceRunStore(registry, tmp_path)
    queue = WorkspaceJobQueue(registry, tmp_path)
    first_run = Run("first-run", payload={"workspace_id": first["id"]})
    second_run = Run("second-run", payload={"workspace_id": second["id"]})
    runs.put(first_run)
    runs.put(second_run)
    queue.enqueue("first-run", {"workspace_id": first["id"]})
    queue.enqueue("second-run", {"workspace_id": second["id"]})

    assert [run.id for run in runs.list()] == ["first-run", "second-run"]
    assert queue.claim("worker").id == "first-run"
    assert queue.cancel("second-run") is True
    assert queue.is_cancelled("second-run") is True

    evidence = WorkspaceEvidenceStores(registry, runs, tmp_path)
    artifact = Artifact("artifact-1", "second-run", "docx", "digest")
    evidence.artifact().put(artifact)
    evidence.finding().put({"id": "finding-1", "run_id": "second-run", "severity": "high"})
    evidence.publication().put({"id": "publication-1", "run_id": "second-run"})

    assert evidence.artifact().get("artifact-1") == artifact
    assert evidence.artifact().list_for_run("second-run") == [artifact]
    assert evidence.finding().list_for_run("second-run")[0]["id"] == "finding-1"
    assert evidence.publication().list_for_workspace(second["id"]) == [{"id": "publication-1", "run_id": "second-run"}]


def test_build_application_degrades_for_an_existing_workspace_without_marker(tmp_path: Path) -> None:
    root = tmp_path / "legacy"  # tmp_path itself is pre-marked by the autouse fixture
    (root / "documents").mkdir(parents=True)
    application = build_application(SidecarConfig(workspace=root))
    assert application.application is None
    assert application.workspace_error == "workspace_marker_missing"
    assert not (root / "workspace.json").exists()


def test_build_application_boots_a_fresh_workspace_and_writes_the_marker(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    application = build_application(SidecarConfig(workspace=root))
    assert application.application is not None
    assert application.workspace_error is None
    assert (root / "workspace.json").is_file()


def test_sidecar_run_is_queued_and_watched_over_a_real_sse_stream(tmp_path: Path) -> None:
    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    server = build_server(config)
    workspace_id = server._docs_application.application.workspace_registry.list()[0]["id"]
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    scope = f"workspace_id={workspace_id}"

    def post(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            f"{base}{path}", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    try:
        status, _ = post("/v2/documents", {
            "workspace_id": workspace_id, "document_id": "watched", "template": "documento-generico", "title": "W",
        })
        assert status == 201
        status, plan = post(f"/v2/documents/watched/plan?{scope}", {})
        assert status == 200 and plan["stages"], plan
        status, created = post(f"/v2/documents/watched/run?{scope}", {})
        assert status == 202 and created["links"]["progress"] == f"/v2/runs/{created['id']}/progress", created
        # The worker process drives the run to a terminal state (a failure is terminal too); the
        # stream must end by itself with a `terminal` event rather than hang the connection.
        stream = urllib.request.urlopen(f"{base}{created['links']['progress']}?{scope}", timeout=120)  # hang guard
        with stream:
            assert stream.headers["Content-Type"].startswith("text/event-stream")
            text = stream.read().decode("utf-8")
        assert "event: progress" in text and text.rstrip().rsplit("event: ", 1)[1].startswith("terminal")
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_sidecar_serves_evidence_baseline_and_inspect_from_real_workspace_stores(tmp_path: Path) -> None:
    import hashlib

    from PIL import Image

    from docs.domain.runtime_records import Passport

    health_app = build_application(SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path))
    try:
        app = health_app.application
        workspace = app.workspace_registry.list()[0]
        wid, root = workspace["id"], Path(workspace["root"])
        run = Run("run-q", "succeeded", {"workspace_id": wid, "document_id": "doc"}, "")
        app.run_store.put(run)
        app.passport_store.put(Passport("run-q", ({"stage": "verify"},)))
        previews = root / "output" / "qa" / "run-q"
        previews.mkdir(parents=True)
        png = previews / "page-1.png"
        Image.new("RGB", (4, 4)).save(png)
        digest = hashlib.sha256(png.read_bytes()).hexdigest()
        app.artifact_store.put(Artifact(
            "run-q-preview-0", "run-q", "preview", digest, "image/png", {"value": {"path": str(png)}},
        ))

        def call(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
            response = app.dispatch(Request(method, f"{path}?workspace_id={wid}", body=body))
            return response.status, json.loads(response.body)

        status, evidence = call("GET", "/v2/runs/run-q/evidence")
        assert status == 200 and evidence["artifacts"][0]["digest"] == digest
        assert evidence["previews"] == {"available": True, "artifact_ids": ["run-q-preview-0"]}
        assert str(root) not in json.dumps(evidence)

        status, inspected = call("GET", "/v2/artifacts/run-q-preview-0/inspect")
        assert status == 200 and inspected["sha256"] == digest and inspected["path"] == "output/qa/run-q/page-1.png"

        status, promoted = call("POST", "/v2/baselines/promotions", {"run_id": "run-q", "name": "golden"})
        assert status == 201 and promoted["destination"] == "baselines/golden"
        assert (root / "baselines" / "golden" / "page-1.png").read_bytes() == png.read_bytes()
        assert call("POST", "/v2/baselines/promotions", {"run_id": "run-q", "name": "golden"})[0] == 409
        assert call("GET", "/v2/baselines")[0] == 200  # the PNG directory does not break the JSON listing
    finally:
        health_app.shutdown()
