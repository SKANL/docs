"""Specialist document tools shared by the CLI and the HTTP API.

`build-ledger`, `review-rules` and `doctor` used to carry their logic inline in
the CLI adapter; both surfaces now call these functions so the output cannot
drift.  `deps` is the application composition, `resolved` a resolved document
context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.doctor import DoctorResult
from docs.domain.review import ReviewResult
from docs.domain.rules import review_rules


def write_fact_ledger(deps: Any, resolved: Any) -> Path:
    """Write the fact ledger: confirmed context plus the evidence already collected."""
    path = Path(resolved.config["paths"]["fact_ledger"])
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = deps.context.confirmed_lines(resolved.doc_id, resolved.template)
    path.write_text(deps.evidence.render_fact_ledger(resolved.config, lines), encoding="utf-8")
    return path


def check_rules(deps: Any, resolved: Any, *, strict: bool) -> ReviewResult:
    """Check that the rules manifest exists and agrees with the template."""
    manifest_exists, manifest_size = deps.rules_manifest_state(resolved.config)
    return review_rules(resolved.template, manifest_exists, manifest_size, strict=strict)


def run_diagnostics(deps: Any, resolved: Any, *, strict: bool = False) -> DoctorResult:
    """Workspace readiness plus the native v2 capability report (what `doctor` prints)."""
    result = deps.doctor.run_doctor(resolved.doc_id, resolved.config, strict=strict)
    output = resolved.config.get("output", {})
    output_format = output.get("format", "docx") if isinstance(output, dict) else "docx"
    try:
        renderer = deps.resolve_renderer(resolved.config)
    except (AttributeError, TypeError, ValueError):
        renderer = None
    registry = deps.create_capability_registry(
        renderer,
        str(output_format),
        deps.workspace.doc_root(resolved.doc_id),
        resolved.config.get("paths", {}),
    )
    result.capabilities = dict(sorted(registry.report().items()))
    result.capability_diagnostics = dict(sorted(registry.diagnostics().items()))
    return result
