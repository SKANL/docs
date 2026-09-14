"""Declarative compatibility policy for the public flat pipeline command."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FlatPipelineRoute:
    """The explicitly supported backend for one legacy CLI stage set."""

    stage_set: str
    backend: str
    operation: str
    expected_stages: tuple[str, ...]


FLAT_PIPELINE_ROUTES: tuple[FlatPipelineRoute, ...] = (
    FlatPipelineRoute("ingest", "v2-source", "ingest", ("ingest-sources",)),
    FlatPipelineRoute(
        "prepare",
        "v2-source",
        "prepare",
        ("ingest-sources", "normalize-sources", "compile-structure"),
    ),
)


def route_for(stage_set: str) -> FlatPipelineRoute | None:
    """Return a v2 route only for a safely equivalent, supported stage set."""

    return next((route for route in FLAT_PIPELINE_ROUTES if route.stage_set == stage_set), None)


def strict_policy_error(policy: Any, invocation_strict: bool) -> str | None:
    """Return the structural error for an invalid v2 strict-policy report."""

    if not isinstance(policy, Mapping):
        return "strict_policy must be a mapping."
    requested = policy.get("requested")
    applied = policy.get("applied")
    mode = policy.get("mode")
    if not isinstance(requested, bool) or not isinstance(applied, bool):
        return "requested and applied must be booleans."
    if requested != invocation_strict:
        return "requested must match invocation strict."
    if mode not in {"enforced", "advisory"}:
        return "mode must be enforced or advisory."
    if applied and (not requested or mode != "enforced"):
        return "applied true requires requested true and mode enforced."
    if not applied and mode != "advisory":
        return "applied false requires advisory mode."
    return None
