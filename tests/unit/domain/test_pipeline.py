from __future__ import annotations

import pytest

from docs.domain.pipeline import pipeline_stage_plan


def test_pipeline_stage_plan_prep_has_nine_stages_in_order():
    stages = pipeline_stage_plan("prep")
    assert [name for name, _ in stages] == [
        "doctor", "build-rules", "review-rules", "collect-sources",
        "collect-code-evidence", "collect-issues", "build-ledger",
        "build-sections", "pack-context",
    ]


def test_pipeline_stage_plan_prep_fail_fast_flags_match_legacy():
    stages = dict(pipeline_stage_plan("prep"))
    assert stages["doctor"] is True
    assert stages["review-rules"] is True
    assert stages["build-rules"] is False
    assert stages["build-sections"] is False


def test_pipeline_stage_plan_assemble_has_three_fail_fast_stages():
    stages = pipeline_stage_plan("assemble")
    assert [name for name, _ in stages] == ["build-docx", "format-audit-docx", "qa-docx"]
    assert all(fail_fast for _, fail_fast in stages)


def test_pipeline_stage_plan_all_is_prep_plus_review_document_plus_assemble():
    stages = pipeline_stage_plan("all")
    names = [name for name, _ in stages]
    assert names == [
        "doctor", "build-rules", "review-rules", "collect-sources",
        "collect-code-evidence", "collect-issues", "build-ledger",
        "build-sections", "pack-context", "review-document",
        "build-docx", "format-audit-docx", "qa-docx",
    ]
    assert dict(stages)["review-document"] is True


def test_pipeline_stage_plan_unknown_stage_set_raises_value_error():
    with pytest.raises(ValueError, match="Conjunto de etapas desconocido: bogus. Usa prep, assemble o all."):
        pipeline_stage_plan("bogus")
