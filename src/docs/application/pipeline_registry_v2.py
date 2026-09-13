"""Registry and planning seams for declarative v2 pipelines."""

from __future__ import annotations

import re
from collections.abc import Mapping

from docs.domain.pipeline_kernel import PipelineDefinition

_PIPELINE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class PipelineRegistryV2:
    """Own named pipeline definitions without coupling them to execution."""

    def __init__(self, definitions: Mapping[str, PipelineDefinition] | None = None) -> None:
        self._definitions: dict[str, PipelineDefinition] = {}
        for pipeline_id, definition in (definitions or {}).items():
            self.register(pipeline_id, definition)

    def register(self, pipeline_id: str, definition: PipelineDefinition) -> None:
        if not isinstance(pipeline_id, str) or _PIPELINE_ID.fullmatch(pipeline_id) is None:
            raise ValueError(f"Invalid pipeline id: {pipeline_id!r}")
        if pipeline_id in self._definitions:
            raise ValueError(f"Pipeline {pipeline_id!r} is already registered")
        definition.validate()
        self._definitions[pipeline_id] = definition

    def get(self, pipeline_id: str) -> PipelineDefinition:
        try:
            return self._definitions[pipeline_id]
        except KeyError as exc:
            raise KeyError(f"Unknown pipeline: {pipeline_id}") from exc

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))


class PipelinePlannerV2:
    """Expose the domain DAG planner as an application boundary."""

    def plan(self, definition: PipelineDefinition) -> tuple[str, ...]:
        return definition.plan()
