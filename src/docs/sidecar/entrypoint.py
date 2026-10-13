"""Command-line entrypoint of the packaged sidecar."""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import signal
import sys
from typing import Any

from docs.sidecar.app import build_server, run
from docs.sidecar.config import SidecarConfig

LOG = logging.getLogger("docs.sidecar")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    multiprocessing.freeze_support()
    # A desktop/self-hosted sidecar must remain responsive when Java is
    # installed but the optional OpenDataLoader JVM bridge stalls. The
    # pypdfium2 text-layer path is deterministic and is the safe default for
    # the long-running server process; deployments that explicitly manage
    # the converter can opt back in with DOCS_PDF_FAST_FALLBACK=0.
    os.environ.setdefault("DOCS_PDF_FAST_FALLBACK", "1")
    config = SidecarConfig.from_args(sys.argv[1:] if argv is None else argv)
    server = build_server(config)

    def request_shutdown(signum: int, frame: Any) -> None:
        del frame
        LOG.info(json.dumps({"event": "sidecar_shutdown_requested", "signal": signum}, sort_keys=True))
        server.shutdown()

    previous: dict[int, Any] = {}
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            number = getattr(signal, name)
            previous[number] = signal.signal(number, request_shutdown)
    try:
        run(server)
    finally:
        application = getattr(server, "_docs_application", None)
        if application is not None:
            application.shutdown()
        for number, handler in previous.items():
            signal.signal(number, handler)
    return 0
