from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, ClassVar

import pytest

import docs.sidecar as sidecar
from docs.api.http import Request
from docs.domain.runtime_records import Artifact, Run
from docs.domain.workspace import Workspace
from docs.sidecar import SidecarConfig, _persist_worker_evidence, build_application, build_server, run


@pytest.fixture(autouse=True)
def _canonical_workspace_root(canonical_workspace_root: Path) -> None:
    """Opt this module into canonical temporary workspaces."""


def test_api_document_creation_composes_the_requested_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from docs.api.http import Request
    from docs.application.workspaces import WorkspaceRegistry
    from docs.domain.models.document import Document

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    registry_path = tmp_path / ".docs" / "workspaces.json"
    registry = WorkspaceRegistry(registry_path)
    first = registry.create("First", first_root)
    second = registry.create("Second", second_root)
    registry.select(first["id"])
    calls: list[Workspace] = []

    class Documents:
        def create(self, document_id: str, template: str, title: str) -> Document:
            return Document(id=document_id, title=title, template=template)

    class Composition:
        documents = Documents()

    def compose(workspace: Workspace) -> Composition:
        calls.append(workspace)
        return Composition()

    monkeypatch.setattr("docs.composition.compose_application", compose)
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
    from docs.application.workspaces import WorkspaceRegistry

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    registry_path = tmp_path / ".docs" / "workspaces.json"
    registry = WorkspaceRegistry(registry_path)
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

    monkeypatch.setattr("docs.composition.compose_application", compose)
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

    monkeypatch.setattr(sidecar, "compose_application", lambda workspace: calls.append(workspace) or application)

    runner = sidecar._build_worker(
        tmp_path,
        object(),
        tmp_path / "worker.sqlite3",
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
    _persist_worker_evidence(passports, artifacts, findings, Result())

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

    assert application.application.run_store.path == tmp_path / ".docs" / "x20.sqlite3"
    assert application.application.queue.path == tmp_path / ".docs" / "x20.sqlite3"
    assert application.application.passport_store.path == tmp_path / ".docs" / "x20.sqlite3"
    assert application.application.artifact_store.path == tmp_path / ".docs" / "x20.sqlite3"
    assert application.application.graph_store.path == tmp_path / ".docs" / "x20.sqlite3"


def test_sidecar_empty_graph_is_an_empty_graph(tmp_path: Path) -> None:
    from docs.application.workspaces import WorkspaceRegistry

    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    server = build_server(config)
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()
    try:
        workspace_id = WorkspaceRegistry(tmp_path / ".docs" / "workspaces.json").list()[0]["id"]
        url = f"http://127.0.0.1:{server.server_address[1]}/v2/graph?workspace_id={workspace_id}"
        with urllib.request.urlopen(url, timeout=2) as response:
            assert json.load(response) == {"nodes": [], "edges": []}
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_filesystem_stores_follow_the_selected_workspace_and_ignore_invalid_manifests(tmp_path: Path) -> None:
    """The sidecar reads each canonical workspace boundary, never process cwd state."""
    from docs.application.workspaces import WorkspaceRegistry
    from docs.sidecar import _FilesystemDocumentStore, _FilesystemTemplateStore

    registry = WorkspaceRegistry(tmp_path / ".docs" / "workspaces.json")
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

    documents = _FilesystemDocumentStore(tmp_path, registry)
    templates = _FilesystemTemplateStore(tmp_path, registry)

    assert documents.list() == [{"title": "Second", "id": "second"}]
    assert documents.get("second") == {"title": "Second", "id": "second"}
    assert documents.get("missing") is None
    assert documents.list_for_workspace(first_root) == [{"title": "First", "id": "first"}]
    template = next(item for item in templates.list_for_workspace(second["id"]) if item["id"] == "template")
    assert template["id"] == "template"
    assert template["version"] == "2"
    assert template["source_path"].endswith("template.json")


def test_workspace_json_collection_reads_revision_lists_and_promotes_only_real_baselines(tmp_path: Path) -> None:
    from docs.application.workspaces import WorkspaceRegistry
    from docs.sidecar import _WorkspaceJsonCollectionStore

    registry = WorkspaceRegistry(tmp_path / ".docs" / "workspaces.json")
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

    baseline_store = _WorkspaceJsonCollectionStore(tmp_path, "baselines", registry)
    revision_store = _WorkspaceJsonCollectionStore(tmp_path, "revisions", registry)

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


def test_workspace_backed_stores_reject_noncanonical_roots(tmp_path: Path) -> None:
    from docs.application.workspaces import WorkspaceRegistry, WorkspaceRegistryError
    from docs.sidecar import _WorkspaceRunStore

    registry = WorkspaceRegistry(tmp_path / ".docs" / "workspaces.json")
    workspace = registry.create("Workspace", tmp_path / "workspace")
    (Path(workspace["root"]) / "workspace.json").unlink()

    with pytest.raises(WorkspaceRegistryError, match="workspace_marker_missing"):
        _WorkspaceRunStore(registry).put(Run("run", payload={"workspace_id": workspace["id"]}))


def test_workspace_runtime_and_evidence_stores_keep_records_in_the_run_workspace(tmp_path: Path) -> None:
    from docs.application.workspaces import WorkspaceRegistry
    from docs.sidecar import _WorkspaceEvidenceStores, _WorkspaceJobQueue, _WorkspaceRunStore

    registry = WorkspaceRegistry(tmp_path / ".docs" / "workspaces.json")
    first = registry.create("First", tmp_path / "first")
    second = registry.create("Second", tmp_path / "second")
    runs = _WorkspaceRunStore(registry, tmp_path)
    queue = _WorkspaceJobQueue(registry, tmp_path)
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

    evidence = _WorkspaceEvidenceStores(registry, runs, tmp_path)
    artifact = Artifact("artifact-1", "second-run", "docx", "digest")
    evidence.artifact().put(artifact)
    evidence.finding().put({"id": "finding-1", "run_id": "second-run", "severity": "high"})
    evidence.publication().put({"id": "publication-1", "run_id": "second-run"})

    assert evidence.artifact().get("artifact-1") == artifact
    assert evidence.artifact().list_for_run("second-run") == [artifact]
    assert evidence.finding().list_for_run("second-run")[0]["id"] == "finding-1"
    assert evidence.publication().list_for_workspace(second["id"]) == [{"id": "publication-1", "run_id": "second-run"}]
