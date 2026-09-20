from __future__ import annotations

from types import SimpleNamespace

from docs.api.application import X20Application
from docs.cli import _shared
from docs.cli._shared import Deps
from docs.domain.workspace import Workspace
from docs.workers import composition


class _Queue:
    def enqueue(self, job):
        return job


class _Leases:
    pass


def _api_kwargs():
    return {
        "run_store": object(),
        "queue": object(),
        "passport_store": object(),
        "artifact_store": object(),
        "graph_store": object(),
    }


def test_cli_composition_invokes_environment_observability_factory(monkeypatch, tmp_path):
    marker = object()
    monkeypatch.setattr(_shared, "create_observability_from_env", lambda: marker)
    workspace = Workspace(tmp_path / "documents", tmp_path / "templates")

    dependencies = Deps(workspace)

    assert dependencies.observability is marker


def test_api_composition_invokes_environment_observability_factory(monkeypatch):
    marker = object()
    monkeypatch.setattr(
        "docs.api.application.create_observability_from_env",
        lambda: marker,
    )

    application = X20Application(**_api_kwargs())

    assert application.observability is marker


def test_worker_composition_invokes_environment_observability_factory(monkeypatch, tmp_path):
    marker = object()
    monkeypatch.setattr(
        "docs.workers.composition.create_observability_from_env",
        lambda: marker,
    )

    service = composition.WorkerComposition(
        lambda _pipeline_id: SimpleNamespace(run=lambda *_args, **_kwargs: None),
        tmp_path,
        _Queue(),
        _Leases(),
    ).create_service()

    assert service.observability is marker
