from docs.application.stage_provider_v2 import StageProviderV2


def test_explicit_stage_service_takes_precedence_over_compatibility_container():
    direct = object()
    provider = StageProviderV2({"example": direct})

    assert provider.get("example") is direct


def test_missing_stage_service_is_reported_as_none():
    assert StageProviderV2({}).get("missing") is None
