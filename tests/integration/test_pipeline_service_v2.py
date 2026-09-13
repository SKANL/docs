from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

from docs.application.atomic_transform_v2 import AtomicTransform
from docs.application.pipeline_service_v2 import (
    FULL_STAGE_IDS,
    PipelineServiceV2,
    PublicationSpec,
)
from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.tool_capability import ToolCapabilityRegistry

STAGE_IDS = (
    "resolve-config",
    "resolve-template",
    "resolve-context",
    "resolve-assets",
    "validate-contracts",
    "ingest-sources",
    "normalize-sources",
    "compile-structure",
    "generate-visuals",
    "compose-cover",
    "build-docx",
    "build-html",
    "build-pdf",
    "structural-audit",
    "editorial-review",
    "evidence-review",
    "consistency-review",
    "accessibility-review",
    "visual-review",
    "reproducibility-check",
    "record-provenance",
    "package-release",
    "publish-draft",
)


def _stage(name: str, calls: list[str], ok: bool = True) -> Callable[[], tuple[bool, str]]:
    def run() -> tuple[bool, str]:
        calls.append(name)
        return ok, name

    return run


def _dependencies(tmp_path: Path, calls: list[str], *, verification_ok: bool = True) -> SimpleNamespace:
    destination = tmp_path / "published" / "document.txt"

    def publish(scratch: Path) -> None:
        calls.append("publish")
        (scratch / "document.txt").write_text("published document", encoding="utf-8")

    return SimpleNamespace(
        resolve_config=_stage("resolve-config", calls),
        resolve_template=_stage("resolve-template", calls),
        resolve_context=_stage("resolve-context", calls),
        resolve_assets=_stage("resolve-assets", calls),
        validate_contracts=_stage("validate-contracts", calls),
        ingest_sources=_stage("ingest-sources", calls),
        normalize_sources=_stage("normalize-sources", calls),
        compile_structure=_stage("compile-structure", calls),
        render=_stage("render", calls),
        build_html=_stage("build-html", calls),
        build_pdf=_stage("build-pdf", calls),
        audit=_stage("audit", calls),
        verify=_stage("verify", calls, ok=verification_ok),
        evidence_review=_stage("evidence-review", calls),
        consistency_review=_stage("consistency-review", calls),
        accessibility_review=_stage("accessibility-review", calls),
        visual_review=_stage("visual-review", calls),
        reproducibility_check=_stage("reproducibility-check", calls),
        provenance=_stage("provenance", calls),
        publication=PublicationSpec(
            expected_outputs=("document.txt",),
            destinations=(destination,),
            operation=publish,
        ),
    )


def _service(
    tmp_path: Path, dependencies: SimpleNamespace, policy: PipelinePolicy | None = None
) -> PipelineServiceV2:
    stage_names = {
        "resolve_config": "resolve-config",
        "resolve_template": "resolve-template",
        "resolve_context": "resolve-context",
        "resolve_assets": "resolve-assets",
        "validate_contracts": "validate-contracts",
        "ingest_sources": "ingest-sources",
        "normalize_sources": "normalize-sources",
        "compile_structure": "compile-structure",
        "generate_visuals": "generate-visuals",
        "compose_cover": "compose-cover",
        "render": "build-docx",
        "build_html": "build-html",
        "build_pdf": "build-pdf",
        "audit": "structural-audit",
        "structural_audit": "structural-audit",
        "verify": "editorial-review",
        "evidence_review": "evidence-review",
        "consistency_review": "consistency-review",
        "accessibility_review": "accessibility-review",
        "visual_review": "visual-review",
        "reproducibility_check": "reproducibility-check",
        "provenance": "record-provenance",
        "package_release": "package-release",
    }
    operations = {
        stage: getattr(dependencies, attribute)
        for attribute, stage in stage_names.items()
        if getattr(dependencies, attribute, None) is not None
    }
    return PipelineServiceV2(
        operations=operations,
        publication=dependencies.publication,
        capabilities=ToolCapabilityRegistry(()),
        ledger=ProvenanceLedgerV2(tmp_path / "provenance.json"),
        atomic_transform=AtomicTransform(),
        policy=policy,
    )


def _replace_dependencies(dependencies: SimpleNamespace, **changes: object) -> SimpleNamespace:
    return SimpleNamespace(**{**vars(dependencies), **changes})


def test_runs_legacy_adapters_in_v2_order_and_publishes_atomically_after_verification(tmp_path: Path) -> None:
    calls: list[str] = []
    service = _service(tmp_path, _dependencies(tmp_path, calls))

    report = service.run("publish-success")

    assert report.succeeded
    assert calls == [
        "resolve-config",
        "resolve-template",
        "resolve-context",
        "resolve-assets",
        "validate-contracts",
        "ingest-sources",
        "normalize-sources",
        "compile-structure",
        "render",
        "build-html",
        "build-pdf",
        "audit",
        "verify",
        "evidence-review",
        "consistency-review",
        "accessibility-review",
        "visual-review",
        "reproducibility-check",
        "provenance",
        "publish",
    ]
    assert (tmp_path / "published" / "document.txt").read_text(encoding="utf-8") == "published document"
    assert service.definition.plan() == STAGE_IDS


def test_does_not_publish_when_verification_fails(tmp_path: Path) -> None:
    calls: list[str] = []
    service = _service(tmp_path, _dependencies(tmp_path, calls, verification_ok=False))

    report = service.run("publish-blocked")

    assert not report.succeeded
    assert calls == [
        "resolve-config",
        "resolve-template",
        "resolve-context",
        "resolve-assets",
        "validate-contracts",
        "ingest-sources",
        "normalize-sources",
        "compile-structure",
        "render",
        "build-html",
        "build-pdf",
        "audit",
        "verify",
    ]
    assert not (tmp_path / "published" / "document.txt").exists()


def test_exports_reusable_full_stage_ids() -> None:
    assert FULL_STAGE_IDS == STAGE_IDS


def test_exposes_the_full_declarative_stage_plan_with_serial_dependencies(tmp_path: Path) -> None:
    service = _service(tmp_path, _dependencies(tmp_path, []))

    stages = {stage.name: stage for stage in service.definition.stages}

    assert service.definition.plan() == STAGE_IDS
    assert tuple(stage.name for stage in service.definition.stages) == STAGE_IDS
    optional_stages = {"generate-visuals", "compose-cover", "package-release"}
    for previous, current in pairwise(STAGE_IDS):
        previous_output = f"{previous}-complete"
        assert stages[previous].produces == (previous_output,)
        assert stages[current].after == (previous,)
        expected_requires = (previous_output,) if previous not in optional_stages else ()
        assert stages[current].requires == expected_requires


def test_failed_required_stage_blocks_all_dependents_in_the_full_plan(tmp_path: Path) -> None:
    calls: list[str] = []
    service = _service(tmp_path, _dependencies(tmp_path, calls, verification_ok=False))

    report = service.run("required-stage-blocked")

    assert not report.succeeded
    assert report.execution.results[-1].stage == "editorial-review"
    assert calls == [
        "resolve-config",
        "resolve-template",
        "resolve-context",
        "resolve-assets",
        "validate-contracts",
        "ingest-sources",
        "normalize-sources",
        "compile-structure",
        "render",
        "build-html",
        "build-pdf",
        "audit",
        "verify",
    ]
    assert "provenance" not in calls
    assert "publish" not in calls


def test_unimplemented_full_plan_stages_report_unsupported_in_draft_without_changing_legacy_execution(tmp_path: Path) -> None:
    calls: list[str] = []
    service = _service(tmp_path, _dependencies(tmp_path, calls))

    report = service.run("draft-with-migration-gaps")

    unsupported = [result for result in report.execution.results if result.outcome == "unsupported"]
    assert [result.stage for result in unsupported] == ["generate-visuals", "compose-cover", "package-release"]
    assert report.succeeded is True
    assert "publish" in calls
    assert any(result.stage == "publish-draft" and result.ok for result in report.execution.results)


def test_unimplemented_full_plan_stage_blocks_strict_and_release_publication(tmp_path: Path) -> None:
    for mode in (PipelineMode.strict, PipelineMode.release):
        calls: list[str] = []
        service = _service(
            tmp_path / mode.value,
                _replace_dependencies(_dependencies(tmp_path / mode.value, calls), ingest_sources=None),
            PipelinePolicy(mode),
        )

        report = service.run(f"{mode.value}-migration-gap")

        assert report.succeeded is False
        first_failure = next(result for result in report.execution.results if not result.ok)
        assert first_failure.stage == "ingest-sources"
        assert first_failure.outcome == "failed"
        assert first_failure.errors == ("stage unsupported: ingest-sources",)
        assert "render" not in calls
        assert "publish" not in calls


def test_strict_and_release_package_failure_never_runs_publish_side_effect(tmp_path: Path) -> None:
    for mode in (PipelineMode.strict, PipelineMode.release):
        calls: list[str] = []
        dependencies = _replace_dependencies(
            _dependencies(tmp_path / mode.value, calls),
            package_release=_stage("package-release", calls, ok=False),
        )

        report = _service(tmp_path / mode.value, dependencies, PipelinePolicy(mode)).run(
            f"{mode.value}-package-failure"
        )

        assert not report.succeeded
        assert "package-release" in calls
        assert "publish" not in calls
        assert not (tmp_path / mode.value / "published" / "document.txt").exists()


def test_explicit_legacy_handlers_cover_safe_migration_stages(tmp_path: Path) -> None:
    calls: list[str] = []
    dependencies = _replace_dependencies(
        _dependencies(tmp_path, calls),
        generate_visuals=_stage("generate-visuals", calls),
        compose_cover=_stage("compose-cover", calls),
        structural_audit=_stage("structural-audit", calls),
        visual_review=_stage("visual-review", calls),
        accessibility_review=_stage("accessibility-review", calls),
        reproducibility_check=_stage("reproducibility-check", calls),
        build_html=_stage("build-html", calls),
        build_pdf=_stage("build-pdf", calls),
    )

    report = _service(tmp_path, dependencies).run("wired-stages", publish=False)

    assert report.succeeded
    assert calls == [
        "resolve-config",
        "resolve-template",
        "resolve-context",
        "resolve-assets",
        "validate-contracts",
        "ingest-sources",
        "normalize-sources",
        "compile-structure",
        "generate-visuals",
        "compose-cover",
        "render",
        "build-html",
        "build-pdf",
        "structural-audit",
        "verify",
        "evidence-review",
        "consistency-review",
        "accessibility-review",
        "visual-review",
        "reproducibility-check",
        "provenance",
    ]


def test_optional_stage_failure_does_not_block_later_serial_stages(tmp_path: Path) -> None:
    calls: list[str] = []
    dependencies = _replace_dependencies(
        _dependencies(tmp_path, calls),
        generate_visuals=_stage("generate-visuals", calls, ok=False),
        compose_cover=_stage("compose-cover", calls),
    )

    report = _service(tmp_path, dependencies).run("optional-stage-failure", publish=False)

    assert not report.succeeded
    assert "render" in calls
    assert "provenance" in calls
    assert next(result for result in report.execution.results if result.stage == "generate-visuals").ok is False
