from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from docs.application.atomic_transform_v2 import AtomicTransform
from docs.application.pipeline_components_v2 import PUBLIC_PIPELINES, ArtifactStore
from docs.application.pipeline_service_v2 import (
    FULL_STAGE_IDS,
    PipelineServiceV2,
    PublicationSpec,
)
from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.tool_capability import ToolCapability, ToolCapabilityRegistry
from docs.infrastructure.ingest.atomic_file_adapter import AtomicFileAdapter

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
EXPECTED_DAG_PLAN = STAGE_IDS


def _stage(name: str, calls: list[str], ok: bool = True) -> Callable[[], tuple[bool, str]]:
    def run() -> tuple[bool, str]:
        calls.append(name)
        return ok, name

    return run


def test_architecture_stage_order_matches_runtime_authority() -> None:
    architecture = Path(__file__).parents[2] / "docs" / "architecture-v2.md"
    section = architecture.read_text(encoding="utf-8").split(
        "The exported `FULL_STAGE_IDS` declaration has 23 stages. It is the registry's",
    )[1]
    documented = tuple(
        line.strip()
        for line in re.search(r"```text\n(?P<stages>.*?)\n```", section, re.DOTALL).group("stages").splitlines()
        if line.strip()
    )

    assert documented == FULL_STAGE_IDS


def test_architecture_documents_registry_plan_and_published_stage_sequence(tmp_path: Path) -> None:
    architecture = Path(__file__).parents[2] / "docs" / "architecture-v2.md"
    section = architecture.read_text(encoding="utf-8").split(
        "The exported `FULL_STAGE_IDS` declaration has 23 stages. It is the registry's",
    )[1]
    documented_inventory, documented_plan = re.findall(
        r"```text\n(?P<stages>.*?)\n```", section, re.DOTALL
    )
    documented = tuple(line.strip() for line in documented_inventory.splitlines() if line.strip())
    documented_runtime_plan = tuple(
        line.strip() for line in documented_plan.splitlines() if line.strip()
    )
    calls: list[str] = []
    service = _service(tmp_path, _dependencies(tmp_path, calls))

    report = service.run("architecture-order")

    assert documented == FULL_STAGE_IDS
    definition = service.registry.resolve("document").definition
    runtime_plan = definition.plan()
    dependencies = {stage.name: stage.requires for stage in definition.stages}
    assert dependencies["compose-cover"] == ("generate-visuals-complete",)
    assert dependencies["build-docx"] == ("compose-cover-complete",)
    assert dependencies["build-html"] == ("build-docx-complete",)
    assert dependencies["build-pdf"] == ("build-docx-complete",)
    assert documented_runtime_plan == runtime_plan
    assert tuple(result.stage for result in report.execution.results) == documented_runtime_plan
    assert tuple(result.stage for result in report.execution.results if result.outcome == "unsupported") == (
        "generate-visuals",
        "compose-cover",
        "package-release",
    )


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
    tmp_path: Path,
    dependencies: SimpleNamespace,
    policy: PipelinePolicy | None = None,
    capabilities: ToolCapabilityRegistry | None = None,
    artifact_store: ArtifactStore | None = None,
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
        capabilities=capabilities if capabilities is not None else ToolCapabilityRegistry(()),
        ledger=ProvenanceLedgerV2(tmp_path / "provenance.json"),
        atomic_transform=AtomicTransform(),
        policy=policy,
        artifact_store=artifact_store,
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
    assert service.definition.plan() == EXPECTED_DAG_PLAN


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

def test_registers_public_pipeline_boundaries():
    service = _service(Path("."), _dependencies(Path("."), []))
    assert {"document-build", "document-verify", "document-package"} <= set(service.registry.names())


def test_public_catalog_marks_stage_backed_boundaries_and_read_only_artifact_operations():
    stage_backed = {entry.pipeline_id for entry in PUBLIC_PIPELINES if entry.stages}
    read_only = {entry.pipeline_id for entry in PUBLIC_PIPELINES if not entry.stages}

    assert stage_backed == {
        "source-ingest",
        "document-prepare",
        "document-build",
        "document-verify",
        "document-publish",
        "document-package",
    }
    assert read_only == {"document-diff", "document-inspect"}

    service = _service(Path("."), _dependencies(Path("."), []))
    assert all(not service.registry.resolve(name).definition.stages for name in read_only)
    assert all(service.registry.resolve(name).definition.stages for name in stage_backed)



def test_runs_a_registered_public_subdag_without_running_unrelated_stages(tmp_path: Path) -> None:
    calls: list[str] = []
    service = _service(tmp_path, _dependencies(tmp_path, calls))

    report = service.run(
        "public-build",
        pipeline_id="document-build",
        publish=False,
        external_artifacts={"compile-structure-complete"},
    )

    assert report.succeeded
    assert calls == ["render", "build-html", "build-pdf"]
    assert [result.stage for result in report.execution.results] == [
        "generate-visuals", "compose-cover", "build-docx", "build-html", "build-pdf"
    ]


def test_omitted_external_artifacts_fail_closed_for_public_subdag(tmp_path: Path) -> None:
    calls: list[str] = []
    service = _service(tmp_path, _dependencies(tmp_path, calls))

    report = service.run(
        "public-build-with-omitted-prerequisites",
        pipeline_id="document-build",
        publish=False,
    )

    assert report.succeeded is False
    assert calls == []
    assert report.execution.results[0].errors == (
        "required external artifact unavailable: compile-structure-complete",
    )


def test_explicit_empty_external_artifacts_fail_public_subdag_preflight(tmp_path: Path) -> None:
    service = _service(tmp_path, _dependencies(tmp_path, []))

    report = service.run(
        "public-build-without-prerequisites",
        pipeline_id="document-build",
        publish=False,
        external_artifacts=set(),
    )

    assert report.succeeded is False
    assert report.execution.results[0].errors == (
        "required external artifact unavailable: compile-structure-complete",
    )


def test_rejects_public_pipeline_publication_request(tmp_path: Path) -> None:
    service = _service(tmp_path, _dependencies(tmp_path, []))

    try:
        service.run("invalid-public-publication", pipeline_id="document-build", publish=True)
    except ValueError as exc:
        assert "only the full document pipeline" in str(exc)
    else:
        raise AssertionError("expected public pipeline publication to be rejected")

def test_exposes_the_full_declarative_stage_plan_without_artificial_serial_dependencies(tmp_path: Path) -> None:
    service = _service(tmp_path, _dependencies(tmp_path, []))

    stages = {stage.name: stage for stage in service.definition.stages}

    assert service.definition.plan() == EXPECTED_DAG_PLAN
    assert tuple(stage.name for stage in service.definition.stages) == STAGE_IDS
    assert stages["generate-visuals"].after == ()
    assert stages["compose-cover"].requires == ("generate-visuals-complete",)
    assert stages["build-docx"].requires == ("compose-cover-complete",)
    assert stages["build-html"].after == ()
    assert stages["build-pdf"].after == ()
    assert stages["build-html"].requires == ("build-docx-complete",)
    assert stages["build-pdf"].requires == ("build-docx-complete",)
    assert stages["package-release"].optional is True


def test_publication_chain_requires_editorial_quality_gate(tmp_path: Path) -> None:
    service = _service(tmp_path, _dependencies(tmp_path, []))

    stages = {stage.name: stage for stage in service.definition.stages}

    assert "editorial-review-complete" in stages["record-provenance"].requires
    assert "editorial-review-complete" in stages["package-release"].requires
    assert "editorial-review-complete" in stages["publish-draft"].requires


def test_failed_required_stage_blocks_all_dependents_in_the_full_plan(tmp_path: Path) -> None:
    calls: list[str] = []
    service = _service(tmp_path, _dependencies(tmp_path, calls, verification_ok=False))

    report = service.run("required-stage-blocked")

    assert not report.succeeded
    assert report.execution.results[-1].stage == "publish-draft"
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


def test_optional_unavailable_capability_keeps_unsupported_package_release_non_failing(tmp_path: Path) -> None:
    calls: list[str] = []
    service = _service(
        tmp_path,
        _dependencies(tmp_path, calls),
        capabilities=ToolCapabilityRegistry((ToolCapability("release-tool", "definitely-missing"),)),
    )

    report = service.run("optional-unsupported-package-release")

    payload = report.to_dict()
    package_release = next(
        result for result in report.execution.results if result.stage == "package-release"
    )
    assert set(payload) == {"capabilities", "execution", "provenance", "succeeded"}
    assert payload["capabilities"] == {"release-tool": {"available": False, "path": None}}
    assert package_release.ok is True
    assert package_release.outcome == "unsupported"
    assert package_release.errors == ()
    assert report.succeeded is True
    assert "publish" in calls


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


def test_failed_visual_generation_blocks_dependent_cover_and_document_build(tmp_path: Path) -> None:
    calls: list[str] = []
    dependencies = _replace_dependencies(
        _dependencies(tmp_path, calls),
        generate_visuals=_stage("generate-visuals", calls, ok=False),
        compose_cover=_stage("compose-cover", calls),
    )

    report = _service(
        tmp_path,
        dependencies,
        policy=PipelinePolicy(PipelineMode.draft),
    ).run("optional-stage-failure", publish=False)

    assert not report.succeeded
    assert "compose-cover" not in calls
    assert "render" not in calls
    assert "provenance" not in calls
    assert next(result for result in report.execution.results if result.stage == "generate-visuals").ok is False


def test_failed_run_rolls_back_legacy_completion_artifacts_without_losing_previous_evidence(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    dependencies = _replace_dependencies(
        _dependencies(tmp_path, calls),
        accessibility_review=_stage("accessibility-review", calls),
        visual_review=_stage("visual-review", calls),
        reproducibility_check=_stage("reproducibility-check", calls),
        package_release=_stage("package-release", calls, ok=False),
    )
    artifact = tmp_path / "stages" / "accessibility-review-complete.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("previous evidence\n", encoding="utf-8")

    report = _service(tmp_path, dependencies).run("completion-artifact-rollback")

    assert report.succeeded is False
    assert artifact.read_text(encoding="utf-8") == "previous evidence\n"
    assert not (tmp_path / "stages" / "reproducibility-check-complete.json").exists()



def test_adapt_does_not_fabricate_completion_artifacts_for_legacy_stage_results():
    handler = PipelineServiceV2._adapt(
        "resolve-config",
        lambda: (True, "resolved configuration"),
        "resolve-config-complete",
    )

    result = handler()

    assert result.ok is True
    assert result.artifacts == ()


def test_external_artifact_generator_is_materialized_once(tmp_path: Path) -> None:
    calls: list[str] = []
    service = _service(tmp_path, _dependencies(tmp_path, calls))

    report = service.run(
        "generator-prerequisite",
        pipeline_id="document-build",
        publish=False,
        external_artifacts=(item for item in ("compile-structure-complete",)),
    )

    assert report.succeeded
    assert calls == ["render", "build-html", "build-pdf"]


def test_policy_less_publication_capability_failure_preflights_before_side_effects(tmp_path: Path) -> None:
    calls: list[str] = []
    run_ids: list[str] = []
    service = PipelineServiceV2(
        operations={"record-provenance": _stage("provenance", calls)},
        publication=_dependencies(tmp_path, calls).publication,
        capabilities=ToolCapabilityRegistry((ToolCapability("soffice", "definitely-missing", required=True),)),
        ledger=ProvenanceLedgerV2(tmp_path / "provenance.json"),
        atomic_transform=AtomicTransform(),
        run_id_sink=run_ids.append,
    )

    report = service.run("missing-default-capability")

    assert report.succeeded is False
    assert report.execution.results[0].errors == ("required capability unavailable: soffice",)
    assert calls == []
    assert run_ids == []


def test_external_prerequisite_preflight_cleans_up_without_recording_run_id(tmp_path: Path) -> None:
    calls: list[str] = []
    run_ids: list[str] = []
    service = _service(tmp_path, _dependencies(tmp_path, calls))
    service._run_id_sink = run_ids.append
    service._cleanup = lambda: calls.append("cleanup")

    report = service.run(
        "missing-external",
        pipeline_id="document-build",
        publish=False,
        external_artifacts=set(),
    )

    assert report.succeeded is False
    assert report.execution.results[0].errors == (
        "required external artifact unavailable: compile-structure-complete",
    )
    assert calls == ["cleanup"]
    assert run_ids == []


def test_required_pdf_capability_preflight_prevents_provenance_and_run_id_mutation(tmp_path: Path) -> None:
    calls: list[str] = []
    run_ids: list[str] = []
    service = PipelineServiceV2(
        operations={"record-provenance": _stage("provenance", calls)},
        publication=_dependencies(tmp_path, calls).publication,
        capabilities=ToolCapabilityRegistry((ToolCapability("soffice", "definitely-missing", required=True),)),
        ledger=ProvenanceLedgerV2(tmp_path / "provenance.json"),
        atomic_transform=AtomicTransform(),
        policy=PipelinePolicy(PipelineMode.draft),
        run_id_sink=run_ids.append,
        excluded_stages=frozenset(set(FULL_STAGE_IDS) - {"record-provenance"}),
        cleanup=lambda: calls.append("cleanup"),
    )

    report = service.run(
        "missing-pdf-capability",
        external_artifacts=service.definition.external_artifacts,
    )

    assert report.succeeded is False
    assert report.execution.results[0].errors == ("required capability unavailable: soffice",)
    assert calls == ["cleanup"]
    assert run_ids == []


def test_materializes_durable_records_for_successful_non_skipped_stages(tmp_path: Path) -> None:
    calls: list[str] = []
    service = _service(
        tmp_path,
        _dependencies(tmp_path, calls),
        artifact_store=ArtifactStore(tmp_path / "stage-records", AtomicFileAdapter()),
    )

    report = service.run("durable-stage-records")

    succeeded = [
        result
        for result in report.execution.results
        if result.ok and result.outcome == "succeeded"
    ]
    assert all(result.artifacts for result in succeeded)
    records = [record for result in succeeded for record in result.artifacts]
    assert all(
        (Path(record.path) if Path(record.path).is_absolute() else tmp_path / "stage-records" / record.path).is_file()
        for record in records
    )
