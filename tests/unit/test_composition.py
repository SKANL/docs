from dataclasses import fields, is_dataclass
from pathlib import Path

from docs.domain.workspace import Workspace

DEPENDENCY_FIELDS = {
    "workspace",
    "observability",
    "document_repository",
    "context_repository",
    "source_repository",
    "renderers",
    "markdown_normalizer",
    "atomic_file_writer",
    "svg_rasterizer",
    "ingest",
    "visual_renderers",
    "generate_visuals_service",
    "pdf_classifier",
    "pdf_text_editor",
    "pdf_render",
    "assets",
    "evidence",
    "review",
    "collection",
    "context_pack",
    "docx",
    "format_audit",
    "render_verification",
    "qa",
    "doctor",
    "documents",
    "corrections",
    "context",
    "section",
    "status",
    "revision",
    "history",
    "run_recorder",
    "verification",
    "structural_audit_service",
    "rules_manifest_state",
}


def test_application_composition_is_a_typed_dataclass_with_the_complete_dependency_surface() -> None:
    from docs.composition import ApplicationComposition

    assert is_dataclass(ApplicationComposition)
    assert {field.name for field in fields(ApplicationComposition)} == DEPENDENCY_FIELDS
    assert all(field.type is not None for field in fields(ApplicationComposition))


def test_compose_application_preserves_the_cli_dependency_surface(tmp_path: Path) -> None:
    from docs.composition import compose_application

    workspace = Workspace(tmp_path / "documents", tmp_path / "templates")
    observability = object()

    composition = compose_application(workspace=workspace, observability=observability)

    assert composition.workspace is workspace
    assert composition.observability is observability
    assert set(composition.__dataclass_fields__) == DEPENDENCY_FIELDS
    assert all(hasattr(composition, attribute) for attribute in DEPENDENCY_FIELDS)


def test_compose_application_builds_the_source_pipeline_from_its_shared_dependencies(tmp_path: Path) -> None:
    from docs.application.source_pipeline import SourcePipeline
    from docs.composition import compose_application

    composition = compose_application(Workspace(tmp_path / "documents", tmp_path / "templates"))

    source_pipeline = composition.create_source_pipeline()

    assert isinstance(source_pipeline, SourcePipeline)
    assert source_pipeline.ingest_service is composition.ingest


def test_compose_application_resolves_default_workspace_and_observability(monkeypatch, tmp_path: Path) -> None:
    from docs import composition as composition_module

    workspace = Workspace(tmp_path / "documents", tmp_path / "templates")
    observability = object()
    monkeypatch.setattr(composition_module, "build_workspace", lambda: workspace)
    monkeypatch.setattr(composition_module, "create_observability_from_env", lambda: observability)

    composition = composition_module.compose_application()

    assert composition.workspace is workspace
    assert composition.observability is observability
