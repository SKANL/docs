from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy


def test_policy_serialization_is_deterministic_and_release_blocks_warnings():
    policy = PipelinePolicy(PipelineMode.release, warning_codes=("visual.blank",))

    assert policy.to_json() == '{"mode":"release","warning_codes":["visual.blank"]}'
    assert policy.severity("visual.blank", "warning") == "error"
    assert policy.severity("other", "warning") == "error"
    assert policy.can_publish() is True


def test_draft_allows_optional_missing_capabilities_but_release_does_not():
    assert PipelinePolicy(PipelineMode.draft).capability_failure(optional=True) == "warning"
    assert PipelinePolicy(PipelineMode.strict).capability_failure(optional=True) == "error"
    assert PipelinePolicy(PipelineMode.release).capability_failure(optional=True) == "error"
