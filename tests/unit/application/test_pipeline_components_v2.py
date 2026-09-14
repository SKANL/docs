from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from docs.application.pipeline_components_v2 import (
    PUBLIC_PIPELINES,
    ArtifactStore,
    PipelinePlanner,
    PipelineRegistry,
    Publication,
    PublicationTransaction,
    RunReporter,
)
from docs.domain.pipeline_kernel import ArtifactContract, PipelineDefinition, StageResult, StageSpec
from docs.infrastructure.ingest.atomic_file_adapter import AtomicFileAdapter


def test_registry_resolves_a_validated_definition_with_its_handlers() -> None:
    definition = PipelineDefinition(stages=(StageSpec("render"),))

    def handler() -> StageResult:
        return StageResult("render", True)

    registry = PipelineRegistry()

    registry.register("document", definition, {"render": handler})

    registered = registry.resolve("document")

    assert registered.definition is definition
    assert registered.handlers["render"] is handler
    with pytest.raises(ValueError, match="already registered"):
        registry.register("document", definition, {"render": handler})


def test_registry_rejects_handlers_for_stages_outside_the_definition() -> None:
    registry = PipelineRegistry()

    with pytest.raises(ValueError, match="handlers reference unknown stages: publish"):
        registry.register(
            "document",
            PipelineDefinition(stages=(StageSpec("render"),)),
            {"publish": lambda: StageResult("publish", True)},
        )


def test_registry_names_and_resolve_are_deterministic() -> None:
    registry = PipelineRegistry()
    alpha = PipelineDefinition(stages=(StageSpec("alpha"),))
    beta = PipelineDefinition(stages=(StageSpec("beta"),))

    registry.register("zeta", beta, {})
    registry.register("alpha", alpha, {})

    assert registry.names() == ("alpha", "zeta")
    assert registry.resolve("alpha").definition is alpha
    with pytest.raises(KeyError, match="pipeline is not registered: missing"):
        registry.resolve("missing")


def test_planner_returns_stage_specs_in_dependency_order() -> None:
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("rendered"),),
        stages=(
            StageSpec("publish", requires=("rendered",)),
            StageSpec("render", produces=("rendered",)),
        ),
    )

    plan = PipelinePlanner().plan(definition)

    assert tuple(stage.name for stage in plan) == ("render", "publish")


def test_planner_uses_stable_topological_order_for_artifact_and_explicit_dependencies() -> None:
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("rendered"),),
        stages=(
            StageSpec("publish", requires=("rendered",), after=("validate",)),
            StageSpec("validate", after=("render",)),
            StageSpec("render", produces=("rendered",)),
            StageSpec("collect"),
        ),
    )

    plan = PipelinePlanner().plan(definition)

    assert tuple(stage.name for stage in plan) == ("collect", "render", "validate", "publish")


def test_artifact_store_writes_a_contract_bound_record(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, AtomicFileAdapter())

    record = store.write(
        ArtifactContract("report", "text/plain"),
        "draft/report.txt",
        b"document body",
        metadata={"format": "txt"},
    )

    assert (tmp_path / "draft" / "report.txt").read_bytes() == b"document body"
    assert record.contract == "report"
    assert record.path == "draft/report.txt"
    assert record.sha256 == hashlib.sha256(b"document body").hexdigest()
    assert record.metadata == {"format": "txt"}


def test_artifact_store_rejects_a_symlinked_parent_that_escapes_the_root(tmp_path: Path) -> None:
    root = tmp_path / "store"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    redirected = root / "redirected"
    try:
        redirected.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    store = ArtifactStore(root, AtomicFileAdapter())

    with pytest.raises(ValueError, match="symlink"):
        store.write(ArtifactContract("report", "text/plain"), "redirected/report.txt", b"body")

    assert not (outside / "report.txt").exists()


def test_artifact_store_rejects_a_symlinked_store_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real-store"
    real_root.mkdir()
    linked_root = tmp_path / "store"
    try:
        linked_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(ValueError, match="symlink"):
        ArtifactStore(linked_root, AtomicFileAdapter())


def test_publication_transaction_publishes_all_requested_artifacts(tmp_path: Path) -> None:
    report = tmp_path / "published" / "report.txt"
    manifest = tmp_path / "published" / "manifest.json"

    result = PublicationTransaction().publish(
        (
            Publication("report.txt", report, b"document body"),
            Publication("manifest.json", manifest, b'{"ok":true}'),
        )
    )

    assert result.ok is True
    assert result.outputs == (report, manifest)
    assert report.read_bytes() == b"document body"
    assert manifest.read_bytes() == b'{"ok":true}'


def test_run_reporter_preserves_ordered_stage_results_in_a_stable_report() -> None:
    report = RunReporter().report(
        (StageResult("render", True), StageResult("publish", False, errors=("blocked",)))
    )

    assert report.to_json() == (
        '{"results":[{"artifacts":[],"errors":[],"ok":true,"outcome":"succeeded",'
        '"stage":"render","warnings":[]},{"artifacts":[],"errors":["blocked"],'
        '"ok":false,"outcome":"failed","stage":"publish","warnings":[]}]}'
    )


def test_public_pipeline_catalog_exposes_reusable_boundaries():
    ids = tuple(spec.pipeline_id for spec in PUBLIC_PIPELINES)
    assert ids == (
        "source-ingest", "document-prepare", "document-build", "document-verify",
        "document-publish", "document-package", "document-diff", "document-inspect",
    )
    assert "build-docx" in next(spec for spec in PUBLIC_PIPELINES if spec.pipeline_id == "document-build").stages


def test_registry_catalog_turns_cross_boundary_requirements_into_external_artifacts() -> None:
    definition = PipelineDefinition(
        artifacts=(
            ArtifactContract("context"),
            ArtifactContract("generate-visuals-complete"),
            ArtifactContract("build-docx-complete"),
        ),
        stages=(
            StageSpec("resolve-context", produces=("context",)),
            StageSpec("generate-visuals", requires=("context",), produces=("generate-visuals-complete",)),
            StageSpec(
                "build-docx",
                requires=("generate-visuals-complete",),
                produces=("build-docx-complete",),
                after=("generate-visuals",),
            ),
        ),
    )
    handlers = {
        name: (lambda name=name: StageResult(name, True))
        for name in ("resolve-context", "generate-visuals", "build-docx")
    }
    registry = PipelineRegistry()

    registry.register_catalog(definition, handlers)

    build = registry.resolve("document-build")
    assert build.definition.plan() == ("generate-visuals", "build-docx")
    assert build.definition.external_artifacts == frozenset({"context"})
    assert tuple(build.handlers) == ("generate-visuals", "build-docx")
    assert build.handlers["generate-visuals"] is handlers["generate-visuals"]
    assert build.handlers["build-docx"] is handlers["build-docx"]


def test_registry_catalog_preserves_external_artifacts_for_standalone_execution() -> None:
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("context"), ArtifactContract("built")),
        stages=(
            StageSpec("resolve-context", produces=("context",)),
            StageSpec("build-docx", requires=("context",), produces=("built",)),
        ),
    )
    registry = PipelineRegistry()
    registry.register_catalog(
        definition,
        {name: lambda name=name: StageResult(name, True) for name in ("resolve-context", "build-docx")},
    )

    build = registry.resolve("document-build")

    assert build.definition.external_artifacts == frozenset({"context"})


def test_artifact_store_writes_deterministic_stage_receipts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, AtomicFileAdapter())
    contract = ArtifactContract("resolve-config-complete")

    record = store.write_stage_receipt(contract, "resolve-config", "resolved configuration")

    assert record.contract == "resolve-config-complete"
    assert record.path == "stages/resolve-config/resolve-config-complete.json"
    assert record.producer_stage == "resolve-config"
    assert (tmp_path / record.path).read_text(encoding="utf-8") == (
        '{"detail":"resolved configuration","stage":"resolve-config"}\n'
    )
