from pathlib import Path
from types import SimpleNamespace

from docs.application.pipeline_assembly import (
    assemble_explicit_stage_operations,
    assemble_pipeline_resources,
    assemble_stage_provider,
)


def test_stage_provider_assembly_registers_shared_stage_services_and_optional_defaults():
    visuals = object()
    composition = SimpleNamespace(generate_visuals_service=visuals, build_html=lambda: None)

    def ensure_assets():
        return True, "assets ready"

    provider = assemble_stage_provider(
        composition,
        config={"paths": {"sections_dir": "sections", "assets_dir": "assets"}},
        output_format="html",
        ensure_assets=ensure_assets,
    )

    assert provider.get("generate_visuals_service") is visuals
    assert provider.get("build_html") is composition.build_html
    assert provider.operation("generate_visuals") is not None
    assert provider.operation("compose_cover") is not None
    assert provider.operation("package_release") is None


def test_pipeline_resources_own_capability_provenance_and_artifact_stores(tmp_path: Path):
    resources = assemble_pipeline_resources(
        renderer=SimpleNamespace(required_capabilities=("pandoc",)),
        output_format="docx",
        document_root=tmp_path,
        document_id="report-id",
        paths={},
        atomic_file_writer=object(),
    )

    assert "pandoc" in {item.name for item in resources.capabilities.capabilities}
    assert resources.ledger._log_path == tmp_path / "runs" / "provenance.json"
    assert resources.artifact_store._root == (tmp_path / "runs" / "v2-stage-artifacts").absolute()
    assert resources.publication._document_id == "report-id"
    assert resources.publication._destination == tmp_path / "output" / "release" / "report-id.zip"
    assert resources.publication._ledger is resources.ledger


def test_explicit_stage_operations_are_registered_by_application_composition():
    callbacks = {
        "structural_audit": lambda: "native-structural",
        "accessibility_review": lambda: "native-accessibility",
        "visual_review": lambda: "native-visual",
        "reproducibility_check": lambda: "native-reproducibility",
        "review_stage": lambda name: lambda: f"review:{name}",
        "build_with_format": lambda format_name: lambda: f"build:{format_name}",
        "render": lambda: "render",
    }
    services = SimpleNamespace(
        structural_audit_service=None,
        structural_audit=lambda: "provided-structural",
        accessibility_review=lambda: "provided-accessibility",
        visual_review=lambda: "provided-visual",
        reproducibility_check=lambda: "provided-reproducibility",
    )
    provider = assemble_stage_provider(
        services, config={}, output_format="docx", ensure_assets=lambda: (True, "ok")
    )

    operations = assemble_explicit_stage_operations(
        provider,
        callbacks=callbacks,
        output_format="docx",
        review_stages_available=False,
    )

    assert operations["structural_audit"]() == "provided-structural"
    assert operations["accessibility_review"]() == "provided-accessibility"
    assert operations["visual_review"]() == "provided-visual"
    assert operations["reproducibility_check"]() == "provided-reproducibility"
    assert operations["build_html"]() == "build:html"
    assert operations["build_pdf"]() == "build:pdf"


def test_explicit_stage_operations_prefer_review_service_when_configured():
    provider = assemble_stage_provider(
        SimpleNamespace(), config={}, output_format="html", ensure_assets=lambda: (True, "ok")
    )
    callbacks = {
        "structural_audit": lambda: "native-structural",
        "accessibility_review": lambda: "native-accessibility",
        "visual_review": lambda: "native-visual",
        "reproducibility_check": lambda: "native-reproducibility",
        "review_stage": lambda name: lambda: f"review:{name}",
        "build_with_format": lambda format_name: lambda: f"build:{format_name}",
        "render": lambda: "render",
    }

    operations = assemble_explicit_stage_operations(
        provider,
        callbacks=callbacks,
        output_format="html",
        review_stages_available=True,
    )

    assert operations["accessibility_review"]() == "review:accessibility-review"
    assert operations["visual_review"]() == "review:visual-review"
    assert operations["reproducibility_check"]() == "review:reproducibility-check"
    assert operations["build_html"]() == "render"
    assert operations["build_pdf"]() == "build:pdf"
