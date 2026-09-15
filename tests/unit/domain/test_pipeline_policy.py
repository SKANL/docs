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


def test_release_keeps_unverifiable_pdf_tag_semantics_as_a_degradable_warning():
    policy = PipelinePolicy(PipelineMode.release)

    assert policy.severity("accessibility.pdf.tags_unverified", "warning") == "warning"


def test_release_keeps_optional_browser_qa_degradations_as_warnings():
    policy = PipelinePolicy(PipelineMode.release)

    assert policy.severity("render.layout.unavailable", "warning") == "warning"
    assert policy.severity("render.image.unverified", "warning") == "warning"
    assert PipelinePolicy(PipelineMode.strict).severity("render.layout.unavailable", "warning") == "error"

