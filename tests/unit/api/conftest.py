"""Shared fixtures for the API unit tests."""

from pathlib import Path

import pytest

from docs.api.application import ApiApplication
from docs.api.http import Request
from docs.composition import compose_application, open_workspace_registry
from docs.domain.workspace import Workspace


class Runs:
    def put(self, item): ...
    def get(self, key): return None
    def list(self): return []


class Queue:
    def enqueue(self, job_id, payload): ...


class Passports:
    def get(self, key): return None


class Artifacts:
    def list(self): return []
    def get(self, key): return None


@pytest.fixture
def stores():
    return {
        "run_store": Runs(), "queue": Queue(), "passport_store": Passports(),
        "artifact_store": Artifacts(),
    }


@pytest.fixture
def api(tmp_path, stores):
    registry = open_workspace_registry(tmp_path / "registry.json")
    workspace = registry.create("Docs", tmp_path / "ws")

    def services(root):
        root = Path(root)
        return compose_application(Workspace(root / "documents", root / "templates", root=root))

    application = ApiApplication(
        **stores, workspace_registry=registry,
        document_service_factory=lambda root: services(root).documents,
        workspace_services_factory=services,
    )
    wid = workspace["id"]
    created = application.dispatch(Request("POST", "/v2/documents", body={
        "workspace_id": wid, "document_id": "doc", "template": "documento-generico", "title": "Doc",
    }))
    assert created.status == 201
    ws_root = Path(workspace["root"])

    def call(method, path, payload=None, **kw):
        sep = "&" if "?" in path else "?"
        return application.dispatch(Request(method, f"{path}{sep}workspace_id={wid}", body=payload, **kw))

    call.app, call.wid, call.ws_root = application, wid, ws_root
    call.doc_root = ws_root / "documents" / "doc"
    return call
