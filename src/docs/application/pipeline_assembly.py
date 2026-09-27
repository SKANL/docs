"""Build the registered stage-provider surface for a document pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docs.application.package_release_service import PackageReleaseService
from docs.application.provenance import ProvenanceLedger
from docs.application.stage_artifact_store import StageArtifactStore
from docs.application.stage_provider import StageProvider
from docs.domain.tool_capability import ToolCapability, ToolCapabilityRegistry


@dataclass(frozen=True)
class PipelineResources:
    capabilities: ToolCapabilityRegistry
    ledger: ProvenanceLedger
    artifact_store: StageArtifactStore
    publication: PackageReleaseService


def assemble_pipeline_resources(
    *,
    renderer: Any,
    output_format: str,
    document_root: Path,
    document_id: str,
    paths: dict[str, object],
    atomic_file_writer: Any,
    artifact: Any = None,
    manifest: Any = None,
    package_writer: Any = None,
    candidate_sink: Any = None,
    verify_current_build: bool = False,
    capability_detector: Any = None,
) -> PipelineResources:
    """Compose durable pipeline state and release publication collaborators."""
    capabilities = list(_renderer_capabilities(renderer))
    capabilities.extend(
        (
            ToolCapability(
                "pillow",
                "",
                module="PIL",
                requirement="required for image inspection",
                degradation="skip image-specific checks",
            ),
            ToolCapability(
                "pypdfium2",
                "",
                module="pypdfium2",
                required=output_format == "pdf",
                requirement="required for PDF page rendering",
                degradation="skip PDF rendering",
            ),
        )
    )
    if output_format == "pdf":
        capabilities.append(
            ToolCapability(
                "soffice",
                "soffice",
                required=True,
                requirement="required to derive PDF from DOCX",
                degradation="skip PDF derivation in draft mode",
            )
        )
    capabilities.extend(_visual_capabilities(document_root))
    registry = ToolCapabilityRegistry(
        capabilities,
        capability_detector,
    )
    ledger = ProvenanceLedger(document_root / "runs" / "provenance.json", trusted_root=document_root)
    store = StageArtifactStore(document_root / "runs" / "v2-stage-artifacts", atomic_file_writer)
    release_root = document_root / "output" / "release"
    publication = PackageReleaseService(
        artifact=artifact or (lambda: None),
        manifest=manifest or (lambda: None),
        document_id=document_id,
        output_format=output_format,
        source_dir=document_root / "output" / "current",
        destination=release_root / f"{document_id}.zip",
        ledger=ledger,
        write_package=package_writer or (lambda candidate, staging: None),
        candidate_sink=candidate_sink or (lambda candidate: None),
        verify_current_build=verify_current_build,
    )
    return PipelineResources(registry, ledger, store, publication)


def _renderer_capabilities(renderer: Any) -> tuple[ToolCapability, ...]:
    declared: list[ToolCapability] = []
    for attribute, required in (("required_capabilities", True), ("optional_capabilities", False)):
        values = getattr(renderer, attribute, ())
        if isinstance(values, str):
            values = (values,)
        if not isinstance(values, (list, tuple, set, frozenset)):
            continue
        for value in values:
            if isinstance(value, ToolCapability):
                declared.append(
                    ToolCapability(value.name, value.executable, required or value.required, module=value.module)
                )
            elif isinstance(value, str) and value:
                declared.append(ToolCapability(value, value, required))
    return tuple(declared)


def _visual_capabilities(document_root: Path) -> tuple[ToolCapability, ...]:
    import json

    try:
        specs = json.loads((document_root / "sections" / "visual-specs.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return ()
    if not isinstance(specs, list):
        return ()
    types = {item.get("type") for item in specs if isinstance(item, Mapping) and isinstance(item.get("type"), str)}
    result = [ToolCapability("resvg", "resvg", degradation="skip vector visual generation")] if types else []
    if "mermaid" in types:
        result.append(ToolCapability("mmdc", "mmdc", degradation="skip Mermaid visual generation"))
    return tuple(result)


_STAGE_SERVICE_NAMES = frozenset(
    {
        "generate_visuals_service",
        "structural_audit_service",
        "rules_manifest_state",
        "generate_visuals",
        "compose_cover",
        "structural_audit",
        "ingest_sources",
        "normalize_sources",
        "compile_structure",
        "build_html",
        "build_pdf",
        "accessibility_review",
        "visual_review",
        "reproducibility_check",
        "evidence_review",
        "consistency_review",
        "package_release",
    }
)


def assemble_stage_provider(
    dependencies: Any,
    *,
    config: Mapping[str, Any],
    output_format: str,
    ensure_assets: Any,
    extra_services: Mapping[str, Any] | None = None,
) -> StageProvider:
    """Register application capabilities and resolve defaults in one place."""
    services = {
        name: service for name in _STAGE_SERVICE_NAMES if (service := getattr(dependencies, name, None)) is not None
    }
    if extra_services:
        services.update(extra_services)
    return StageProvider(
        services,
        config=config,
        output_format=output_format,
        ensure_assets=ensure_assets,
    )


def assemble_explicit_stage_operations(
    stage_provider: StageProvider,
    *,
    callbacks: Mapping[str, Any],
    output_format: str,
    review_stages_available: bool,
) -> dict[str, Any]:
    """Bind stage-provider capabilities and format-aware review operations."""

    def callable_stage(name: str) -> Any:
        operation = stage_provider.get(name)
        return operation if callable(operation) else None

    review_stage = callbacks["review_stage"]
    operations: dict[str, Any] = {
        "generate_visuals": stage_provider.operation("generate_visuals"),
        "compose_cover": stage_provider.operation("compose_cover"),
        "structural_audit": (
            callbacks["structural_audit"]
            if stage_provider.get("structural_audit_service") is not None
            else callable_stage("structural_audit")
        ),
        "accessibility_review": (
            review_stage("accessibility-review")
            if review_stages_available and output_format != "docx"
            else callable_stage("accessibility_review")
            or (
                review_stage("accessibility-review")
                if review_stages_available
                else callbacks["accessibility_review"]
            )
        ),
        "visual_review": (
            review_stage("visual-review")
            if review_stages_available
            else callable_stage("visual_review") or callbacks["visual_review"]
        ),
        "reproducibility_check": (
            callable_stage("reproducibility_check")
            or (
                review_stage("reproducibility-check")
                if review_stages_available
                else callbacks["reproducibility_check"]
            )
        ),
    }
    operations["build_html"] = (
        callbacks["build_with_format"]("html") if output_format != "html" else callbacks["render"]
    )
    operations["build_pdf"] = (
        callbacks["build_with_format"]("pdf") if output_format != "pdf" else callbacks["render"]
    )
    return {name: operation for name, operation in operations.items() if operation is not None}
