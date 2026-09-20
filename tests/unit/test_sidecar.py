from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from docs.domain.contracts import Run
from docs.sidecar import SidecarConfig, build_application, build_server, run


def test_sidecar_defaults_are_loopback_and_protocol_stable() -> None:
    config = SidecarConfig.from_args([])
    assert config.host == "127.0.0.1"
    assert config.port == 8765
    assert config.protocol == "docs-sidecar/v1"


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


def test_sidecar_runs_endpoint_returns_empty_results_without_workspace() -> None:
    config = SidecarConfig(host="127.0.0.1", port=0, workspace=None)
    server = build_server(config)
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1/runs"
        with urllib.request.urlopen(url, timeout=2) as response:
            assert response.status == 200
            assert json.load(response) == {"items": [], "next_cursor": None}
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
