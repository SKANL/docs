"""Resumable document summary shared by `doc status` (CLI) and `GET /v2/documents/{id}/summary`."""

from __future__ import annotations

from typing import Any

from docs.domain.document_status import DocumentStatus
from docs.domain.normative import resolve_normative_settings


def build_document_summary(deps: Any, doc: str) -> tuple[DocumentStatus, dict[str, Any]]:
    """Return the status aggregate and its JSON payload, capability diagnostics included."""
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    result = deps.status.status_summary(resolved.doc_id, resolved.template, resolved.config, normative=normative)
    payload = result.to_dict()
    output = resolved.config.get("output", {})
    output_format = output.get("format", "docx") if isinstance(output, dict) else "docx"
    invalid_format_diagnostic: dict[str, str | bool | None] | None = None
    try:
        renderer = deps.resolve_renderer(resolved.config)
    except (AttributeError, TypeError, ValueError):
        renderer = None
        invalid_format_diagnostic = {
            "available": False,
            "path": None,
            "required": True,
            "policy": "required",
            "kind": "format",
            "version": None,
            "diagnostic": f"Formato de salida no registrado: '{output_format}'.",
            "requirement": "a registered output renderer",
            "degradation": "diagnostics only; rendering remains unavailable",
        }
    registry = deps.create_capability_registry(
        renderer,
        str(output_format),
        deps.workspace.doc_root(resolved.doc_id),
        resolved.config.get("paths", {}),
    )
    capabilities = registry.report()
    capability_diagnostics = registry.diagnostics()
    if invalid_format_diagnostic is not None:
        capabilities["output_format"] = {"available": False, "path": None}
        capability_diagnostics["output_format"] = invalid_format_diagnostic
    v2 = payload.get("v2", {})
    current_v2 = dict(v2) if isinstance(v2, dict) else {}
    payload["v2"] = {**current_v2, "capabilities": capabilities, "capability_diagnostics": capability_diagnostics}
    return result, payload
