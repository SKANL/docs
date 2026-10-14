from __future__ import annotations

from docs import composition as application_composition
from docs.api.application import ApiApplication
from docs.composition import ApplicationComposition
from docs.domain.workspace import Workspace


def _api_kwargs():
    return {
        "run_store": object(),
        "queue": object(),
        "passport_store": object(),
        "artifact_store": object(),
        "graph_store": object(),
    }


def test_cli_composition_invokes_environment_observability_factory(
    monkeypatch, canonical_workspace_root
):
    tmp_path = canonical_workspace_root
    marker = object()
    monkeypatch.setattr(application_composition, "create_observability_from_env", lambda: marker)
    workspace = Workspace(tmp_path / "documents", tmp_path / "templates")

    dependencies = ApplicationComposition(workspace)

    assert dependencies.observability is marker


def test_api_composition_invokes_environment_observability_factory(monkeypatch):
    marker = object()
    monkeypatch.setattr(
        "docs.api.application.create_observability_from_env",
        lambda: marker,
    )

    application = ApiApplication(**_api_kwargs())

    assert application.observability is marker
