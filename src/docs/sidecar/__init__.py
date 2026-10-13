"""Desktop sidecar: the local Docs API plus its worker process."""

from docs.sidecar.app import build_application, build_server, run
from docs.sidecar.config import SidecarConfig
from docs.sidecar.entrypoint import main

__all__ = ("SidecarConfig", "build_application", "build_server", "main", "run")
