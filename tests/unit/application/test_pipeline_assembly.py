from types import SimpleNamespace

from docs.application.pipeline_assembly import assemble_stage_provider


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
