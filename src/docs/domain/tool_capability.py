"""Pure capability declarations, policy evaluation, and stable reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from docs.domain.ports.tool_capability_detector_port import ToolCapabilityDetectorPort

if TYPE_CHECKING:
    from docs.domain.pipeline_policy import PipelinePolicy


class CapabilityPolicyState(StrEnum):
    """Whether a declared capability is optional or required by a pipeline."""

    optional = "optional"
    required = "required"


@dataclass(frozen=True, slots=True)
class ToolCapability:
    """Typed declaration for one local executable or Python module capability."""

    name: str
    executable: str
    required: bool = False
    module: str | None = None
    requirement: str | None = None
    degradation: str | None = None
    policy: CapabilityPolicyState = CapabilityPolicyState.optional

    def __post_init__(self) -> None:
        policy = CapabilityPolicyState(self.policy)
        if self.required:
            policy = CapabilityPolicyState.required
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "required", policy is CapabilityPolicyState.required)


@dataclass(frozen=True, slots=True)
class CapabilityDetection:
    """Infrastructure-supplied observation of one capability without policy."""

    available: bool
    path: str | None = None
    version: str | None = None
    diagnostic: str | None = None

    @classmethod
    def available_at(cls, path: str, *, version: str | None = None) -> CapabilityDetection:
        return cls(True, path=path, version=version)

    @classmethod
    def unavailable(cls, diagnostic: str | None = None) -> CapabilityDetection:
        return cls(False, diagnostic=diagnostic)


@dataclass(frozen=True, slots=True)
class CapabilityPolicyEvaluation:
    """Stable policy decision for the capabilities observed in one run."""

    mode: str
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        return bool(self.errors)

    def to_dict(self) -> dict[str, object]:
        return {
            "blocking": self.blocking,
            "errors": list(self.errors),
            "mode": self.mode,
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class _UnavailableCapabilityDetector:
    """Safe default for unit callers that did not compose native infrastructure."""

    def detect(self, capability: ToolCapability) -> CapabilityDetection:
        return CapabilityDetection.unavailable(f"Capability detector not configured: {capability.name}")


@dataclass(slots=True)
class ToolCapabilityRegistry:
    """Lazily evaluate declared capabilities through an injected detector port."""

    capabilities: tuple[ToolCapability, ...] | list[ToolCapability]
    detector: ToolCapabilityDetectorPort = field(default_factory=_UnavailableCapabilityDetector)
    _resolved: dict[str, CapabilityDetection] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        merged: dict[str, ToolCapability] = {}
        for capability in sorted(self.capabilities, key=lambda item: item.name):
            existing = merged.get(capability.name)
            if existing is not None:
                for field_name in ("executable", "module", "degradation"):
                    if getattr(existing, field_name) != getattr(capability, field_name):
                        raise ValueError(
                            f"distinct duplicate capability {capability.name!r}: "
                            f"{field_name} differs"
                        )
            merged[capability.name] = capability if existing is None else ToolCapability(
                name=existing.name,
                executable=existing.executable,
                required=existing.required or capability.required,
                module=existing.module or capability.module,
                requirement=existing.requirement or capability.requirement,
                degradation=existing.degradation or capability.degradation,
                policy=(
                    CapabilityPolicyState.required
                    if CapabilityPolicyState.required in {existing.policy, capability.policy}
                    else CapabilityPolicyState.optional
                ),
            )
        self.capabilities = tuple(merged.values())

    def _detect(self, capability: ToolCapability) -> CapabilityDetection:
        if capability.name not in self._resolved:
            self._resolved[capability.name] = self.detector.detect(capability)
        return self._resolved[capability.name]

    def report(self) -> dict[str, dict[str, str | bool | None]]:
        """Return compact, name-sorted capability availability for existing consumers."""
        return {
            capability.name: {
                "available": (detection := self._detect(capability)).available,
                "path": detection.path,
            }
            for capability in self.capabilities
        }

    def diagnostics(self) -> dict[str, dict[str, str | bool | None]]:
        """Return deterministic policy and diagnostic details for humans and CI."""
        return {
            capability.name: {
                "available": (detection := self._detect(capability)).available,
                "path": detection.path,
                "required": capability.required,
                "policy": capability.policy.value,
                "kind": "module" if capability.module else "executable",
                "version": detection.version,
                "diagnostic": detection.diagnostic,
                "requirement": capability.requirement,
                "degradation": capability.degradation,
            }
            for capability in self.capabilities
        }

    def missing_required(self) -> tuple[str, ...]:
        return tuple(
            capability.name
            for capability in self.capabilities
            if capability.policy is CapabilityPolicyState.required and not self._detect(capability).available
        )

    def evaluate(self, policy: PipelinePolicy) -> CapabilityPolicyEvaluation:
        """Evaluate all unavailable capabilities against draft/strict/release policy."""
        warnings: list[str] = []
        errors: list[str] = []
        for capability in self.capabilities:
            if self._detect(capability).available:
                continue
            message = f"{capability.policy.value} capability unavailable: {capability.name}"
            target = warnings if policy.capability_failure(
                optional=capability.policy is CapabilityPolicyState.optional
            ) == "warning" else errors
            target.append(message)
        return CapabilityPolicyEvaluation(policy.mode.value, tuple(warnings), tuple(errors))
