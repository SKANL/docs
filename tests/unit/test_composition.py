from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from docs.domain.workspace import Workspace
from docs.domain.workspace_format import WorkspaceFormatError, write_workspace_marker


def _workspace(root: Path) -> Workspace:
    write_workspace_marker(root)
    return Workspace(root=root, documents_dir=root / "documents", templates_dir=root / "templates")

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
    "artifact_reports",
    "package_publications",
    "rules_manifest_state",
}


def test_application_composition_is_a_typed_dataclass_with_the_complete_dependency_surface() -> None:
    from docs.composition import ApplicationComposition

    assert is_dataclass(ApplicationComposition)
    assert {field.name for field in fields(ApplicationComposition)} == DEPENDENCY_FIELDS
    assert all(field.type is not None for field in fields(ApplicationComposition))


def test_compose_application_rejects_resolved_unmarked_workspace_without_mutation(
    monkeypatch, tmp_path: Path
) -> None:
    from docs import composition as composition_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DOCS_WORKSPACE_REGISTRY", str(tmp_path / "registry.json"))
    adapter_constructed = False

    def adapter_init(self, *args, **kwargs):
        nonlocal adapter_constructed
        adapter_constructed = True

    monkeypatch.setattr(composition_module.JsonDocumentRepository, "__init__", adapter_init)

    with pytest.raises(WorkspaceFormatError, match="workspace_marker_missing"):
        composition_module.compose_application()

    assert adapter_constructed is False
    assert list(tmp_path.iterdir()) == []


def test_compose_application_rejects_missing_workspace_marker_before_adapter_construction(
    monkeypatch, tmp_path: Path
) -> None:
    from docs import composition as composition_module

    workspace = Workspace(root=tmp_path, documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    adapter_constructed = False

    def adapter_init(self, *args, **kwargs):
        nonlocal adapter_constructed
        adapter_constructed = True

    monkeypatch.setattr(composition_module.JsonDocumentRepository, "__init__", adapter_init)

    with pytest.raises(WorkspaceFormatError, match="workspace_marker_missing"):
        composition_module.compose_application(workspace)

    assert adapter_constructed is False


def test_compose_application_rejects_malformed_workspace_marker(tmp_path: Path) -> None:
    from docs.composition import compose_application

    (tmp_path / "workspace.json").write_text("not-json", encoding="utf-8")
    workspace = Workspace(root=tmp_path, documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")

    with pytest.raises(WorkspaceFormatError, match="workspace_marker_malformed"):
        compose_application(workspace)


def test_compose_application_preserves_the_cli_dependency_surface(tmp_path: Path) -> None:
    from docs.composition import compose_application

    workspace = _workspace(tmp_path)
    observability = object()

    composition = compose_application(workspace=workspace, observability=observability)

    assert composition.workspace is workspace
    assert composition.observability is observability
    assert set(composition.__dataclass_fields__) == DEPENDENCY_FIELDS
    assert all(hasattr(composition, attribute) for attribute in DEPENDENCY_FIELDS)


def test_compose_application_builds_the_source_pipeline_from_its_shared_dependencies(tmp_path: Path) -> None:
    from docs.application.source_pipeline import SourcePipeline
    from docs.composition import compose_application

    composition = compose_application(_workspace(tmp_path))

    source_pipeline = composition.create_source_pipeline()

    assert isinstance(source_pipeline, SourcePipeline)
    assert source_pipeline.ingest_service is composition.ingest


def test_application_composition_owns_stage_provider_registration(tmp_path: Path) -> None:
    from docs.application.stage_provider import StageProvider
    from docs.composition import compose_application

    composition = compose_application(_workspace(tmp_path))
    visual_service = object()
    composition.generate_visuals_service = visual_service

    provider = composition.create_stage_provider(
        config={"paths": {"sections_dir": str(tmp_path / "sections"), "assets_dir": str(tmp_path / "assets")}},
        output_format="docx",
        ensure_assets=lambda: (True, "assets ready"),
    )

    assert isinstance(provider, StageProvider)
    assert provider.get("generate_visuals_service") is visual_service
    assert provider.operation("generate_visuals") is not None


def test_compose_application_disables_visual_generation_without_rasterizer(monkeypatch, tmp_path: Path) -> None:
    from docs.composition import compose_application
    from docs.infrastructure.visuals.resvg_rasterizer_adapter import ResvgRasterizerAdapter

    def fail_to_construct(self, *args, **kwargs):
        raise RuntimeError("resvg adapter unavailable")

    monkeypatch.setattr(ResvgRasterizerAdapter, "__init__", fail_to_construct)

    composition = compose_application(_workspace(tmp_path))

    assert composition.svg_rasterizer is None
    assert composition.generate_visuals_service is None


def test_application_composition_builds_document_pipeline_with_shared_observability(tmp_path: Path) -> None:
    from docs.application.pipeline_service import PipelineService
    from docs.composition import compose_application
    from docs.domain.provenance import ProvenanceLedger
    from docs.domain.tool_capability import ToolCapabilityRegistry

    observability = object()
    composition = compose_application(
        _workspace(tmp_path), observability=observability
    )
    def publish() -> None:
        return None

    pipeline = composition.create_document_pipeline(
        operations={},
        expected_outputs=(),
        destinations=(),
        operation=publish,
        capabilities=ToolCapabilityRegistry(()),
        ledger=ProvenanceLedger(tmp_path / "provenance.json"),
    )

    assert isinstance(pipeline, PipelineService)
    assert pipeline._publication.operation is publish
    assert pipeline._publication.expected_outputs == ()
    assert pipeline._publication.destinations == ()
    assert type(pipeline._atomic_transform).__name__ == "AtomicTransform"
    assert all(executor.observability is observability for executor in pipeline._executors.values())


def test_compose_application_resolves_default_workspace_and_observability(monkeypatch, tmp_path: Path) -> None:
    from docs import composition as composition_module

    workspace = _workspace(tmp_path)
    observability = object()
    monkeypatch.setattr(composition_module, "build_workspace", lambda: workspace)
    monkeypatch.setattr(composition_module, "create_observability_from_env", lambda: observability)

    composition = composition_module.compose_application()

    assert composition.workspace is workspace
    assert composition.observability is observability


def test_application_composition_owns_document_pipeline_use_case(tmp_path: Path) -> None:
    from docs.composition import compose_application

    composition = compose_application(_workspace(tmp_path))

    assert callable(composition.create_document_pipeline_service)
