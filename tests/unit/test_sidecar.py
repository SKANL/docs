from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from docs.sidecar import SidecarConfig, build_server, run


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
