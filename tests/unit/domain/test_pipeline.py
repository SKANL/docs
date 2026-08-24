from __future__ import annotations

import re

import pytest

from docs.domain.pipeline import pipeline_stage_plan

_ASSEMBLE_DOCX_STAGES: list[tuple[str, bool]] = [
    ("build-docx", True),
    ("format-audit-docx", True),
    ("qa-docx", True),
]


def test_pipeline_stage_plan_prep_has_ten_stages_in_order():
    # "gap-report" added Front G (task 11.9, design.md Decision 7) right
    # after "build-sections" -- a deliberate surface growth, not drift.
    stages = pipeline_stage_plan("prep")
    assert [name for name, _ in stages] == [
        "doctor", "build-rules", "review-rules", "collect-sources",
        "collect-code-evidence", "collect-issues", "build-ledger",
        "build-sections", "gap-report", "pack-context",
    ]


def test_pipeline_stage_plan_prep_fail_fast_flags_match_legacy():
    stages = dict(pipeline_stage_plan("prep"))
    assert stages["doctor"] is True
    assert stages["review-rules"] is True
    assert stages["build-rules"] is False
    assert stages["build-sections"] is False
    # strict mode must block on gaps before final output (spec:
    # document-pipeline "Strict mode blocks on gaps").
    assert stages["gap-report"] is True


def test_pipeline_stage_plan_assemble_prepends_generate_visuals_then_caller_supplied_stages():
    # domain/pipeline.py must hold zero format literals: the assemble segment
    # is entirely data supplied by the caller (the resolved renderer), not a
    # hardcoded module-level constant -- but "generate-visuals" (format-
    # agnostic, design.md Decision "generate-visuals is a format-agnostic
    # stage before assemble") is always prepended ahead of it.
    stages = pipeline_stage_plan("assemble", _ASSEMBLE_DOCX_STAGES)
    assert stages == [("generate-visuals", False), *_ASSEMBLE_DOCX_STAGES]


def test_pipeline_stage_plan_assemble_carries_arbitrary_format_stages_unmodified():
    # A distinct, non-DOCX stage tuple flows through untouched, proving the
    # domain layer has no DOCX/"tesina" sentinel baked in.
    txt_stages = [("build-txt", True)]
    assert pipeline_stage_plan("assemble", txt_stages) == [("generate-visuals", False), *txt_stages]


def test_pipeline_stage_plan_all_is_prep_plus_review_document_plus_generate_visuals_plus_assemble():
    stages = pipeline_stage_plan("all", _ASSEMBLE_DOCX_STAGES)
    names = [name for name, _ in stages]
    assert names == [
        "doctor", "build-rules", "review-rules", "collect-sources",
        "collect-code-evidence", "collect-issues", "build-ledger",
        "build-sections", "gap-report", "pack-context", "review-document",
        "generate-visuals", "build-docx", "format-audit-docx", "qa-docx",
    ]
    assert dict(stages)["review-document"] is True
    assert dict(stages)["generate-visuals"] is False


def test_generate_visuals_runs_after_ingest_before_assemble_in_all():
    # "ingest"/build-context-* stages are not part of "all" by design (`all`
    # excludes ingest); the last ingest-set stage is "build-context-index"
    # when the caller runs ingest separately -- what matters for THIS plan is
    # that "generate-visuals" sits strictly after the last prep/review stage
    # ("review-document") and strictly before the first assemble-supplied
    # stage, so the figure catalog (produced by ingest, run earlier as its
    # own stage_set) exists before generate-visuals merges into it, and the
    # resolver (assemble) sees the generated entries.
    stages = pipeline_stage_plan("all", _ASSEMBLE_DOCX_STAGES)
    names = [name for name, _ in stages]
    assert names.index("generate-visuals") == names.index("review-document") + 1
    assert names.index("generate-visuals") == names.index("build-docx") - 1


def test_generate_visuals_prepended_before_assemble_stages_in_assemble():
    stages = pipeline_stage_plan("assemble", _ASSEMBLE_DOCX_STAGES)
    names = [name for name, _ in stages]
    assert names[0] == "generate-visuals"
    assert names[1:] == [name for name, _ in _ASSEMBLE_DOCX_STAGES]


def test_generate_visuals_is_fail_fast_false():
    stages = dict(pipeline_stage_plan("assemble", _ASSEMBLE_DOCX_STAGES))
    assert stages["generate-visuals"] is False


def test_pipeline_stage_plan_unknown_stage_set_raises_value_error():
    with pytest.raises(ValueError, match=re.escape("Conjunto de etapas desconocido: bogus. Usa prep, assemble, all o ingest.")):
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
    assert second == [("generate-visuals", False), *_ASSEMBLE_DOCX_STAGES]
    assert _ASSEMBLE_DOCX_STAGES == [
        ("build-docx", True),
        ("format-audit-docx", True),
        ("qa-docx", True),
    ]
