from pathlib import Path

from docs.domain.workspace import Workspace


def test_compose_application_preserves_the_cli_dependency_surface(tmp_path: Path) -> None:
    from docs.composition import compose_application

    workspace = Workspace(tmp_path / "documents", tmp_path / "templates")
    observability = object()

    composition = compose_application(workspace=workspace, observability=observability)

    assert composition.workspace is workspace
    assert composition.observability is observability
    for attribute in (
        "document_repository",
        "context_repository",
        "source_repository",
        "assets",
        "documents",
        "section",
        "ingest",
        "renderers",
        "verification",
    ):
        assert hasattr(composition, attribute)


def test_compose_application_resolves_a_workspace_when_none_is_supplied(monkeypatch, tmp_path: Path) -> None:
    from docs import composition as composition_module

    workspace = Workspace(tmp_path / "documents", tmp_path / "templates")
    monkeypatch.setattr(composition_module, "build_workspace", lambda: workspace)

    assert composition_module.compose_application().workspace is workspace
