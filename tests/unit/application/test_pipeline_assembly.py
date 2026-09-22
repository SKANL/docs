from pathlib import Path
from types import SimpleNamespace

from docs.application.pipeline_assembly import (
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
        paths={},
        atomic_file_writer=object(),
    )

    assert "pandoc" in {item.name for item in resources.capabilities.capabilities}
    assert resources.ledger._log_path == tmp_path / "runs" / "provenance.json"
    assert resources.artifact_store._root == (tmp_path / "runs" / "v2-stage-artifacts").absolute()
    assert resources.publication._destination == tmp_path / "output" / "release" / f"{tmp_path.name}.zip"
    assert resources.publication._ledger is resources.ledger
