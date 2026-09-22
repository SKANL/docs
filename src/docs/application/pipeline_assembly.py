"""Build the registered stage-provider surface for a document pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from docs.application.stage_provider import StageProvider

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
        name: service
        for name in _STAGE_SERVICE_NAMES
        if (service := getattr(dependencies, name, None)) is not None
    }
    if extra_services:
        services.update(extra_services)
    return StageProvider(
        services,
        config=config,
        output_format=output_format,
        ensure_assets=ensure_assets,
    )
