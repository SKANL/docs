"""Provide v2 stages through one composition-root adapter boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from docs.domain.cover import CoverMode, resolve_cover_spec
from docs.domain.pipeline_kernel import StageResult


class StageProviderV2:
    """Resolve a stage service without leaking composition details to stages."""

    def __init__(
        self,
        services: Mapping[str, Any],
        *,
        config: Mapping[str, Any] | None = None,
        output_format: str = "docx",
        ensure_assets: Any | None = None,
    ) -> None:
        self._services = dict(services)
        self._config = config or {}
        self._output_format = output_format
        self._ensure_assets = ensure_assets

    def get(self, name: str) -> Any:
        """Return the explicitly registered service for ``name`` if callable."""
        return self._services.get(name)

    def operation(self, name: str) -> Any:
        """Resolve a reusable operation, including safe optional stage defaults."""
        explicit = self._services.get(name)
        if name == "generate_visuals" and self._services.get("generate_visuals_service") is not None:
            return self._generate_visuals
        if explicit is not None:
            return explicit
        if name == "generate_visuals":
            return self._generate_visuals
        if name == "compose_cover":
            return self._compose_cover
        return None

    def _generate_visuals(self) -> tuple[bool, str] | StageResult:
        if self._ensure_assets is not None:
            assets_result = self._ensure_assets()
            if not assets_result[0]:
                return assets_result
        service = self._services.get("generate_visuals_service")
        if service is None or not hasattr(service, "generate"):
            return StageResult.skipped("generate-visuals")
        paths = self._config.get("paths", {})
        sections_dir = paths.get("sections_dir") if isinstance(paths, Mapping) else None
        assets_dir = paths.get("assets_dir") if isinstance(paths, Mapping) else None
        if not isinstance(sections_dir, str) or not isinstance(assets_dir, str):
            return StageResult.skipped("generate-visuals")
        result = service.generate(Path(sections_dir), Path(assets_dir))
        return True, f"{result.generated} generated, {result.skipped} skipped"

    def _compose_cover(self) -> tuple[bool, str] | StageResult:
        spec = resolve_cover_spec(dict(self._config))
        if spec is None or spec.mode is not CoverMode.GENERATED:
            return StageResult.skipped("compose-cover")
        if self._output_format != "docx":
            return True, f"cover composition delegated to {self._output_format} renderer"
        return True, "cover composition delegated to native DOCX compositor"
