from docs.application.stage_provider_v2 import StageProviderV2
from docs.domain.pipeline_kernel import StageResult


def test_explicit_stage_service_takes_precedence_over_compatibility_container():
    direct = object()
    provider = StageProviderV2({"example": direct})

    assert provider.get("example") is direct


def test_missing_stage_service_is_reported_as_none():
    assert StageProviderV2({}).get("missing") is None


def test_generate_visuals_operation_is_owned_by_the_application_provider(tmp_path):
    calls = []

    class Visuals:
        def generate(self, sections_dir, assets_dir):
            calls.append((sections_dir, assets_dir))
            return type("Result", (), {"generated": 2, "skipped": 1})()

    provider = StageProviderV2(
        {"generate_visuals_service": Visuals()},
        config={"paths": {"sections_dir": str(tmp_path / "sections"), "assets_dir": str(tmp_path / "assets")}},
    )

    result = provider.operation("generate_visuals")()

    assert result == (True, "2 generated, 1 skipped")
    assert calls == [(tmp_path / "sections", tmp_path / "assets")]


def test_generate_visuals_without_capability_is_gracefully_unsupported(tmp_path):
    provider = StageProviderV2(
        {},
        config={"paths": {"sections_dir": str(tmp_path / "sections"), "assets_dir": str(tmp_path / "assets")}},
    )

    result = provider.operation("generate_visuals")()

    assert isinstance(result, StageResult)
    assert result.stage == "generate-visuals"
    assert result.outcome == "skipped"


def test_compose_cover_operation_is_owned_by_the_application_provider():
    result = StageProviderV2({}, config={"cover": {"mode": "none"}}).operation("compose_cover")()

    assert isinstance(result, StageResult)
    assert result.stage == "compose-cover"
    assert result.outcome == "skipped"


def test_package_release_operation_is_owned_by_the_application_provider():
    calls = []

    class PackageRelease:
        def release(self):
            calls.append("package")
            return True, "package ready"

    provider = StageProviderV2({"package_release_service": PackageRelease()})

    assert provider.operation("package_release")() == (True, "package ready")
    assert calls == ["package"]
