"""Resolved pipeline plan shared by the CLI (`document plan`) and the HTTP API."""

from __future__ import annotations

from typing import Any


def describe_pipeline(service: Any, pipeline_id: str) -> dict[str, Any]:
    """Return the stages and external contracts of a registered pipeline.

    Raises `KeyError` when `pipeline_id` is not registered.
    """
    definition = service.registry.resolve(pipeline_id).definition
    return {
        "pipeline_id": pipeline_id,
        "stages": list(definition.plan()),
        "external_artifacts": sorted(definition.external_artifacts),
        "contracts": [contract.to_dict() for contract in definition.artifacts],
    }
