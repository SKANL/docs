"""Compose the sidecar: stores, API application, worker process and HTTP server."""

from __future__ import annotations

import json
import logging
import multiprocessing
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from docs.api.application import ApiApplication
from docs.api.http import Router
from docs.api.server import GracefulHTTPServer, TransportConfig, create_server, serve
from docs.application.workspaces import WorkspaceRegistry, WorkspaceRegistryError
from docs.composition import open_workspace_registry
from docs.infrastructure.persistence.idempotency import SqliteIdempotencyStore
from docs.plugins.registry import PluginRegistry
from docs.sidecar.config import SidecarConfig
from docs.sidecar.document_actions import DocumentActions, workspace_services
from docs.sidecar.health import HealthApplication
from docs.sidecar.roots import state_path
from docs.sidecar.stores import (
    FilesystemDocumentStore,
    FilesystemTemplateStore,
    WorkspaceEvidenceStores,
    WorkspaceGraphStore,
    WorkspaceJobQueue,
    WorkspaceJsonCollectionStore,
    WorkspaceRunStore,
)
from docs.sidecar.worker import worker_process_main

LOG = logging.getLogger("docs.sidecar")


def _seed_builtin_templates(workspace_root: Path) -> None:
    """Make a fresh desktop workspace immediately usable by the import UI."""
    templates = workspace_root / "templates"
    templates.mkdir(parents=True, exist_ok=True)
    if any(templates.glob("*.json")):
        return
    package = files("docs.templates.builtin")
    for entry in package.iterdir():
        if entry.name.endswith(".json"):
            (templates / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")


def _unavailable(config: SidecarConfig, error: str) -> HealthApplication:
    return HealthApplication(None, urlsplit(config.health_url).path, config.protocol, workspace_error=error)


def _open_registry(workspace: Path) -> tuple[WorkspaceRegistry, dict[str, Any]]:
    registry = open_workspace_registry(workspace / ".docs" / "workspaces.json")
    configured = registry.ensure("Local workspace", workspace)
    return registry, configured


def build_application(config: SidecarConfig) -> HealthApplication:
    if config.workspace is None:
        return _unavailable(config, "workspace_not_configured")
    try:
        registry, configured_workspace = _open_registry(config.workspace)
    except WorkspaceRegistryError as exc:
        # An unusable workspace degrades /health instead of killing the process.
        return _unavailable(config, exc.code)
    _seed_builtin_templates(config.workspace)
    # Plugin discovery is optional and declarative: manifests are inspected
    # without importing or executing plugin code. The core remains fully
    # operational when the workspace has no plugins.
    plugin_registry = PluginRegistry()
    plugin_registry.discover([config.workspace / "plugins"])
    if registry.active() is None:
        registry.select(str(configured_workspace["id"]))
    application = _build_api_application(config, registry, plugin_registry)
    return HealthApplication(
        application,
        urlsplit(config.health_url).path,
        config.protocol,
        worker_thread=_start_worker_process(config.workspace),
    )


def _build_api_application(
    config: SidecarConfig, registry: WorkspaceRegistry, plugin_registry: PluginRegistry
) -> ApiApplication:
    assert config.workspace is not None
    run_store = WorkspaceRunStore(registry, config.workspace)
    evidence_stores = WorkspaceEvidenceStores(registry, run_store, config.workspace)
    actions = DocumentActions(registry)
    return ApiApplication(
        run_store=run_store,
        queue=WorkspaceJobQueue(registry, config.workspace),
        passport_store=evidence_stores.passport(),
        artifact_store=evidence_stores.artifact(),
        graph_store=WorkspaceGraphStore(registry, config.workspace),
        # The core sidecar remains plugin-independent. Plugin discovery is an
        # optional application concern and must never be required to start or
        # execute the document pipeline.
        plugin_registry=plugin_registry,
        findings_store=evidence_stores.finding(),
        publication_store=evidence_stores.publication(),
        template_store=FilesystemTemplateStore(config.workspace, registry),
        baseline_store=WorkspaceJsonCollectionStore(config.workspace, "baselines", registry),
        revision_store=WorkspaceJsonCollectionStore(config.workspace, "revisions", registry),
        document_store=FilesystemDocumentStore(config.workspace, registry),
        workspace_registry=registry,
        managed_workspace_root=config.workspace / ".docs" / "workspaces",
        document_service_factory=actions.document_service,
        document_action=actions.run_action,
        document_context_reader=actions.read_context,
        document_context_writer=actions.set_context,
        revision_service=actions.revise,
        workspace_services_factory=workspace_services,
        router=Router(
            cors_origins=config.cors_origins,
            max_body_size=config.max_body_bytes,
            idempotency_persistence=SqliteIdempotencyStore(state_path(config.workspace)),
        ),
    )


def _start_worker_process(workspace: Path) -> multiprocessing.process.BaseProcess:
    # Heavy document work runs in a separate process. A Python thread would
    # share the GIL with HTML/PDF parsing and could make the API appear dead
    # while the worker is healthy but busy. Always spawn: a forked child (the
    # POSIX default) inherits this process's open SQLite connections and fails
    # with "disk I/O error" on its first write.
    process = multiprocessing.get_context("spawn").Process(
        target=worker_process_main,
        args=(workspace,),
        name="docs-worker",
        daemon=True,
    )
    process.start()
    return process


def build_server(config: SidecarConfig) -> GracefulHTTPServer:
    transport = TransportConfig(
        host=config.host,
        port=config.port,
        mode="offline",
        workspace=config.workspace,
        max_request_body=120 * 1024 * 1024,
        cors_origins=config.cors_origins,
    )
    application = build_application(config)
    server = create_server(application, transport)
    server._docs_application = application  # type: ignore[attr-defined]
    return server


def run(server: GracefulHTTPServer) -> None:
    LOG.info(json.dumps({"event": "sidecar_started", "address": server.server_address}, default=str, sort_keys=True))
    try:
        serve(server)
    finally:
        LOG.info(json.dumps({"event": "sidecar_stopped"}, sort_keys=True))
