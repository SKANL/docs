"""Resolve the document inputs consumed by the canonical build pipeline."""

from __future__ import annotations

import json
from collections.abc import Callable, MutableMapping
from copy import deepcopy
from pathlib import Path
from typing import Any


class DocumentInputStageService:
    """Own input resolution and source/contract stages for a document build."""

    def __init__(
        self,
        *,
        document_id: str,
        document_root: Path,
        output_format: str,
        state: MutableMapping[str, Any],
        resolve_context: Callable[[], Any],
        resolve_renderer: Callable[[dict[str, Any]], Any],
        figure_pipeline: Any = None,
        source_pipeline: Any = None,
        fallback_stage: Callable[[str], Any] | None = None,
    ) -> None:
        self._document_id = document_id
        self._document_root = document_root
        self._output_format = output_format
        self._state = state
        self._resolve_context = resolve_context
        self._resolve_renderer = resolve_renderer
        self._figure_pipeline = figure_pipeline
        self._source_pipeline = source_pipeline
        self._fallback_stage = fallback_stage

    def resolve_config(self) -> tuple[bool, str]:
        resolved = self._resolve_context()
        self._state["resolved"] = resolved
        config = deepcopy(resolved.config)
        config.setdefault("output", {})["format"] = self._output_format
        self._state["config"] = config
        self._state["renderer"] = self._resolve_renderer(config)
        return True, f"document={resolved.doc_id}"

    def resolve_template(self) -> tuple[bool, str]:
        resolved = self._state["resolved"]
        return True, f"template={resolved.template.type}"

    def resolve_context_stage(self) -> tuple[bool, str]:
        resolved = self._state["resolved"]
        return True, f"document={resolved.doc_id}"

    def resolve_assets(self) -> tuple[bool, str]:
        """Rebuild a missing derived figure catalog from existing authored assets."""
        configured_paths = self._state["config"].get("paths", {})
        sections_dir = Path(configured_paths.get("sections_dir", self._document_root / "sections"))
        catalog_path = sections_dir / "figure-catalog.json"
        bindings_path = sections_dir / "figure-bindings.json"
        if self._figure_pipeline is not None and bindings_path.is_file():
            try:
                catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.is_file() else {}
                if not catalog.get("figures"):
                    assets_dir = Path(configured_paths.get("assets_dir", self._document_root / "assets")) / "figures"
                    candidates = (
                        tuple(
                            (path, path.relative_to(self._document_root).as_posix())
                            for path in sorted(assets_dir.iterdir(), key=lambda item: item.name)
                            if path.is_file() and path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".svg"}
                        )
                        if assets_dir.is_dir()
                        else ()
                    )
                    if candidates:
                        self._figure_pipeline.build_figure_catalog_for(
                            Path(configured_paths.get("inbox_dir", self._document_root / "inbox")),
                            sections_dir,
                            list(candidates),
                            [],
                            entries=[],
                            assets_dir=None,
                        )
                        return True, f"catalogued {len(candidates)} existing figure assets"
            except (OSError, TypeError, ValueError, AttributeError) as exc:
                return False, f"could not resolve existing figure assets: {exc}"
        return True, "resolve-assets completed"

    def source_stage(self, name: str) -> tuple[bool, str]:
        if self._source_pipeline is not None:
            return self._source_pipeline.run_stage(
                name, self._document_id, self._document_root, self._state["config"]
            )
        operation = self._fallback_stage(name.replace("-", "_")) if self._fallback_stage else None
        if operation is None:
            return False, f"{name} service is not configured"
        return operation()

    def validate_contracts(self) -> tuple[bool, str]:
        resolved = self._state["resolved"]
        if getattr(self._state["renderer"], "output_format", "") != self._output_format:
            return False, f"renderer does not provide {self._output_format} output"
        return True, f"document={resolved.doc_id}"
