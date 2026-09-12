"""Pure contracts and planning kernel for the next-generation pipeline."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, cast

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class CycleError(ValueError):
    """Raised when stage dependencies cannot be ordered."""


def _check_identifier(value: str, kind: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid {kind} identifier: {value!r}")
    return value


def _stable(value: Any) -> Any:
    if is_dataclass(value):
        return _stable(asdict(cast(Any, value)))
    if isinstance(value, dict):
        return {str(key): _stable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (set, frozenset, tuple, list)):
        items = [_stable(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True)) if isinstance(value, (set, frozenset)) else items
    return value


def deterministic_json(value: Any) -> str:
    """Serialize supported domain values with a stable, compact JSON shape."""
    return json.dumps(_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


serialize = deterministic_json


@dataclass(frozen=True)
class ArtifactContract:
    name: str
    media_type: str = "application/octet-stream"
    required: bool = False

    def __post_init__(self) -> None:
        _check_identifier(self.name, "artifact")
        if not self.media_type:
            raise ValueError("Artifact media_type must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return _stable(asdict(self))

    def to_json(self) -> str:
        return deterministic_json(self)


@dataclass(frozen=True)
class ArtifactRecord:
    contract: str
    path: str
    sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _check_identifier(self.contract, "artifact")
        if not self.path:
            raise ValueError("Artifact path must not be empty")
        if not re.fullmatch(r"[0-9a-f]{64}|[0-9a-f]+", self.sha256):
            raise ValueError("Artifact sha256 must be a lowercase hexadecimal digest")

    def to_dict(self) -> dict[str, Any]:
        return _stable(asdict(self))

    def to_json(self) -> str:
        return deterministic_json(self)


@dataclass(frozen=True)
class StageSpec:
    name: str
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    fail_fast: bool = True
    optional: bool = False
    after: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _check_identifier(self.name, "stage")
        for artifact in (*self.requires, *self.produces):
            _check_identifier(artifact, "artifact")
        for predecessor in self.after:
            _check_identifier(predecessor, "stage")
        if self.name in self.after or len(set(self.after)) != len(self.after):
            raise ValueError(f"Stage {self.name!r} contains invalid ordering dependencies")
        if len(set(self.requires)) != len(self.requires) or len(set(self.produces)) != len(self.produces):
            raise ValueError(f"Stage {self.name!r} contains duplicate artifact references")

    def to_dict(self) -> dict[str, Any]:
        return _stable(asdict(self))


@dataclass(frozen=True)
class StageResult:
    stage: str
    ok: bool
    artifacts: tuple[ArtifactRecord, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    outcome: str = "succeeded"

    def __post_init__(self) -> None:
        _check_identifier(self.stage, "stage")
        if self.outcome not in {"succeeded", "failed", "skipped", "unsupported"}:
            raise ValueError(f"Invalid stage outcome: {self.outcome!r}")
        if self.ok:
            if self.errors:
                raise ValueError("A successful stage cannot contain errors")
            if self.outcome == "failed":
                raise ValueError("A successful stage cannot have a failed outcome")
            return
        if self.outcome in {"skipped", "unsupported"}:
            raise ValueError("Skipped or unsupported stages must be non-failing results")
        object.__setattr__(self, "outcome", "failed")

    @classmethod
    def skipped(cls, stage: str) -> StageResult:
        """Return a visible, non-failing intentional skip."""
        return cls(stage, True, warnings=(f"stage skipped: {stage}",), outcome="skipped")

    @classmethod
    def unsupported(cls, stage: str) -> StageResult:
        """Return a visible, non-failing implementation gap."""
        return cls(stage, True, warnings=(f"stage unsupported: {stage}",), outcome="unsupported")

    def to_dict(self) -> dict[str, Any]:
        return _stable(asdict(self))

    def to_json(self) -> str:
        return deterministic_json(self)


@dataclass(frozen=True)
class PipelineDefinition:
    artifacts: tuple[ArtifactContract, ...] = ()
    stages: tuple[StageSpec, ...] = ()
    external_artifacts: frozenset[str] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        return _stable(asdict(self))

    def to_json(self) -> str:
        return deterministic_json(self)

    def validate(self) -> None:
        contracts = {contract.name for contract in self.artifacts}
        if len(contracts) != len(self.artifacts):
            raise ValueError("Pipeline contains duplicate artifact contracts")
        names = {stage.name for stage in self.stages}
        if len(names) != len(self.stages):
            raise ValueError("Pipeline contains duplicate stage names")
        unknown_external = self.external_artifacts - contracts
        if unknown_external:
            raise ValueError(f"Unknown external artifacts: {', '.join(sorted(unknown_external))}")
        produced: dict[str, str] = {}
        stage_names = {stage.name for stage in self.stages}
        for stage in self.stages:
            unknown_predecessors = set(stage.after) - stage_names
            if unknown_predecessors:
                raise ValueError(
                    f"Stage {stage.name!r} orders after unknown stage(s): "
                    + ", ".join(sorted(unknown_predecessors))
                )
            for artifact in stage.produces:
                if artifact not in contracts:
                    raise ValueError(f"Stage {stage.name!r} produces unknown artifact {artifact!r}")
                if artifact in produced:
                    raise ValueError(f"Artifact {artifact!r} has multiple producers: {produced[artifact]!r}, {stage.name!r}")
                produced[artifact] = stage.name
            for artifact in stage.requires:
                if artifact not in contracts:
                    raise ValueError(f"Stage {stage.name!r} requires unknown artifact {artifact!r}")
                if artifact not in produced and artifact not in self.external_artifacts and not any(artifact in other.produces for other in self.stages):
                    raise ValueError(f"Stage {stage.name!r} requires unavailable artifact {artifact!r}")
        missing_required = sorted(
            contract.name
            for contract in self.artifacts
            if contract.required
            and contract.name not in produced
            and contract.name not in self.external_artifacts
        )
        if missing_required:
            raise ValueError(
                "required artifact(s) must have a producer: " + ", ".join(missing_required)
            )

    def plan(self) -> tuple[str, ...]:
        self.validate()
        producers = {artifact: stage.name for stage in self.stages for artifact in stage.produces}
        dependencies: dict[str, set[str]] = {stage.name: set() for stage in self.stages}
        dependents: dict[str, set[str]] = {stage.name: set() for stage in self.stages}
        for stage in self.stages:
            for predecessor in stage.after:
                dependencies[stage.name].add(predecessor)
                dependents[predecessor].add(stage.name)
            for artifact in stage.requires:
                producer = producers.get(artifact)
                if producer and producer != stage.name:
                    dependencies[stage.name].add(producer)
                    dependents[producer].add(stage.name)
        ready = sorted(name for name, deps in dependencies.items() if not deps)
        ordered: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for dependent in sorted(dependents[current]):
                dependencies[dependent].remove(current)
                if not dependencies[dependent]:
                    ready.append(dependent)
                    ready.sort()
        if len(ordered) != len(self.stages):
            remaining = sorted(name for name in dependencies if name not in ordered)
            raise CycleError(f"Pipeline stage cycle detected: {', '.join(remaining)}")
        return tuple(ordered)
