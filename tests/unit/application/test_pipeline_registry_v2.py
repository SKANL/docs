from __future__ import annotations

import pytest

from docs.application.pipeline_registry_v2 import PipelinePlannerV2, PipelineRegistryV2
from docs.domain.pipeline_kernel import PipelineDefinition, StageSpec


def _definition(name: str = "example") -> PipelineDefinition:
    return PipelineDefinition(stages=(StageSpec(name),))


def test_registry_returns_registered_definition_and_stable_ids() -> None:
    registry = PipelineRegistryV2()
    registry.register("example", _definition())

    assert registry.get("example") == _definition()
    assert registry.ids() == ("example",)


def test_registry_rejects_duplicate_or_invalid_definitions() -> None:
    registry = PipelineRegistryV2()
    registry.register("example", _definition())

    with pytest.raises(ValueError, match="already registered"):
        registry.register("example", _definition())
    with pytest.raises(ValueError, match="pipeline id"):
        registry.register("Bad ID", _definition())


def test_planner_delegates_to_domain_dag_and_returns_immutable_order() -> None:
    definition = PipelineDefinition(
        stages=(
            StageSpec("build", after=("prepare",)),
            StageSpec("prepare"),
        )
    )

    assert PipelinePlannerV2().plan(definition) == ("prepare", "build")
