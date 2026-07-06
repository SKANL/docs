from __future__ import annotations

import pytest

from docs.domain.pipeline import pipeline_stage_plan

_ASSEMBLE_DOCX_STAGES: list[tuple[str, bool]] = [
    ("build-docx", True),
    ("format-audit-docx", True),
    ("qa-docx", True),
]


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


def test_pipeline_stage_plan_assemble_returns_caller_supplied_stages():
    # domain/pipeline.py must hold zero format literals: the assemble segment
    # is entirely data supplied by the caller (the resolved renderer), not a
    # hardcoded module-level constant.
    stages = pipeline_stage_plan("assemble", _ASSEMBLE_DOCX_STAGES)
    assert stages == _ASSEMBLE_DOCX_STAGES


def test_pipeline_stage_plan_assemble_carries_arbitrary_format_stages_unmodified():
    # A distinct, non-DOCX stage tuple flows through untouched, proving the
    # domain layer has no DOCX/"tesina" sentinel baked in.
    txt_stages = [("build-txt", True)]
    assert pipeline_stage_plan("assemble", txt_stages) == txt_stages


def test_pipeline_stage_plan_all_is_prep_plus_review_document_plus_assemble():
    stages = pipeline_stage_plan("all", _ASSEMBLE_DOCX_STAGES)
    names = [name for name, _ in stages]
    assert names == [
        "doctor", "build-rules", "review-rules", "collect-sources",
        "collect-code-evidence", "collect-issues", "build-ledger",
        "build-sections", "pack-context", "review-document",
        "build-docx", "format-audit-docx", "qa-docx",
    ]
    assert dict(stages)["review-document"] is True


def test_pipeline_stage_plan_unknown_stage_set_raises_value_error():
    with pytest.raises(ValueError, match="Conjunto de etapas desconocido: bogus. Usa prep, assemble, all o ingest."):
        pipeline_stage_plan("bogus")


def test_pipeline_stage_plan_ingest_has_three_stages_in_order():
    # Format-agnostic like `prep`: ingest/context-file generation stage names
    # never vary by output format, so they stay a module constant here
    # rather than a caller-supplied parameter (PR8 task 8.1).
    stages = pipeline_stage_plan("ingest")
    assert [name for name, _ in stages] == ["ingest", "build-context-files", "build-context-index"]


def test_pipeline_stage_plan_ingest_fail_fast_flags_are_all_true():
    stages = dict(pipeline_stage_plan("ingest"))
    assert stages == {"ingest": True, "build-context-files": True, "build-context-index": True}


def test_pipeline_stage_plan_ingest_deterministic_across_repeated_calls():
    first = pipeline_stage_plan("ingest")
    second = pipeline_stage_plan("ingest")
    assert first == second
    first.append(("mutated", False))
    assert second == [("ingest", True), ("build-context-files", True), ("build-context-index", True)]


def test_pipeline_stage_plan_assemble_without_stages_raises_value_error():
    # Omitting `assemble` must be a loud error, not a silent empty stage plan
    # (remediation: fresh-context review finding — silent-empty fallback).
    with pytest.raises(ValueError, match="assemble"):
        pipeline_stage_plan("assemble")


def test_pipeline_stage_plan_all_without_stages_raises_value_error():
    with pytest.raises(ValueError, match="assemble"):
        pipeline_stage_plan("all")


def test_pipeline_stage_plan_deterministic_across_repeated_calls():
    first = pipeline_stage_plan("assemble", _ASSEMBLE_DOCX_STAGES)
    second = pipeline_stage_plan("assemble", _ASSEMBLE_DOCX_STAGES)
    assert first == second
    # returned lists must be independent copies — mutating one must not leak
    # into the next call or into the caller-supplied source list.
    first.append(("mutated", False))
    assert second == _ASSEMBLE_DOCX_STAGES
    assert _ASSEMBLE_DOCX_STAGES == [
        ("build-docx", True),
        ("format-audit-docx", True),
        ("qa-docx", True),
    ]
