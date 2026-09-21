from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from docs.domain.contracts import Run
from docs.api.http import Request
from docs.sidecar import SidecarConfig, build_application, build_server, run


def test_sidecar_defaults_are_loopback_and_protocol_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCS_SIDECAR_WORKSPACE", raising=False)
    monkeypatch.delenv("DOCS_DOCUMENTS_DIR", raising=False)
    config = SidecarConfig.from_args([])
    assert config.host == "127.0.0.1"
    assert config.port == 8765
    assert config.protocol == "docs-sidecar/v1"
    assert "http://localhost:1420" in config.cors_origins


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
            f"http://127.0.0.1:{server.server_address[1]}/v1/runs",
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
    application = build_application(config)
    application.application.run_store.put(Run("run-1", created_at="2026-01-01T00:00:00+00:00"))
    server = build_server(config)
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1/runs"
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
        response = health_app.application.dispatch(Request("GET", "/v1/templates"))
        payload = json.loads(response.body)
        ids = {item["id"] for item in payload["items"]}
        assert response.status == 200
        assert {"documento-generico", "technical-report-srs", "reporte-estadia-tic"} <= ids
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
    config = SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)
    server = build_server(config)
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1/graph"
        with urllib.request.urlopen(url, timeout=2) as response:
            assert json.load(response) == {"nodes": [], "edges": []}
    finally:
        server.shutdown()
        thread.join(timeout=2)
