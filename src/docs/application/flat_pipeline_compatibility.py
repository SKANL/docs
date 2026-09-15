"""Declarative compatibility policy for the public flat pipeline command."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FlatPipelineRoute:
    """The explicitly supported backend for one legacy CLI stage set."""

    stage_set: str
    backend: str
    operation: str
    expected_stages: tuple[str, ...]


class FlatPipelineCompatibilityAdapter:
    """Adapt the historical flat ``all`` contract to explicit v2 boundaries."""

    def __init__(
        self,
        *,
        prep: Callable[[], Mapping[str, Any]],
        review_document: Callable[[], Mapping[str, Any]],
        assemble: Callable[[], Sequence[Mapping[str, Any]]],
    ) -> None:
        self._prep = prep
        self._review_document = review_document
        self._assemble = assemble

    def run_all(self) -> dict[str, Any]:
        stages: list[Mapping[str, Any]] = []
        warnings: list[Any] = []
        errors: list[Any] = []
        strict = False
        for run in (self._prep, self._review_document):
            summary = run()
            strict = summary.get("strict", strict)
            stages.extend(summary.get("stages", []))
            if isinstance(summary.get("warnings"), list):
                warnings.extend(summary["warnings"])
            if isinstance(summary.get("errors"), list):
                errors.extend(summary["errors"])
            if summary.get("passed") is not True:
                result: dict[str, Any] = {
                    "stage_set": "all",
                    "strict": strict,
                    "passed": False,
                    "stages": stages,
                }
                if warnings:
                    result["warnings"] = warnings
                if errors:
                    result["errors"] = errors
                return result
        summaries = self._assemble()
        for summary in summaries:
            stages.extend(summary.get("stages", []))
            if isinstance(summary.get("warnings"), list):
                warnings.extend(summary["warnings"])
            if isinstance(summary.get("errors"), list):
                errors.extend(summary["errors"])
        result = {
            "stage_set": "all",
            "strict": summaries[0].get("strict", strict) if summaries else strict,
            "passed": bool(summaries) and all(summary.get("passed") is True for summary in summaries),
            "stages": stages,
        }
        if warnings:
            result["warnings"] = warnings
        if errors:
            result["errors"] = errors
        return result


FLAT_PIPELINE_ROUTES: tuple[FlatPipelineRoute, ...] = (
    FlatPipelineRoute("ingest", "v2-source", "ingest", ("ingest-sources",)),
    FlatPipelineRoute(
        "prepare",
        "v2-source",
        "prepare",
        ("ingest-sources", "normalize-sources", "compile-structure"),
    ),
    FlatPipelineRoute("assemble", "v2-runtime", "build", ()),
    FlatPipelineRoute("all", "v2-runtime", "all", ("prep", "review-document", "assemble")),
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
