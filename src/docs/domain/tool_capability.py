"""Deterministic, local-only checks for optional external tool capabilities."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ToolCapability:
    """A named executable capability that can be resolved on demand."""

    name: str
    executable: str
    required: bool = False
    module: str | None = None


@dataclass(slots=True)
class ToolCapabilityRegistry:
    """Lazily resolve registered tools and expose a stable capability report."""

    capabilities: tuple[ToolCapability, ...] | list[ToolCapability]
    _resolved: dict[str, str | None] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        merged: dict[str, ToolCapability] = {}
        for capability in sorted(self.capabilities, key=lambda item: item.name):
            existing = merged.get(capability.name)
            merged[capability.name] = (
                capability
                if existing is None
                else ToolCapability(
                    name=existing.name,
                    executable=existing.executable,
                    required=existing.required or capability.required,
                    module=existing.module or capability.module,
                )
            )
        self.capabilities = tuple(merged.values())

    def _resolve(self, capability: ToolCapability) -> str | None:
        if capability.name not in self._resolved:
            if capability.module:
                self._resolved[capability.name] = (
                    f"python:{capability.module}"
                    if importlib.util.find_spec(capability.module) is not None
                    else None
                )
            else:
                self._resolved[capability.name] = shutil.which(capability.executable)
        return self._resolved[capability.name]

    def report(self) -> dict[str, dict[str, str | bool | None]]:
        """Return capabilities sorted by name, resolving each at most once."""
        return {
            capability.name: {
                "available": (path := self._resolve(capability)) is not None,
                "path": path,
            }
            for capability in self.capabilities
        }

    def missing_required(self) -> tuple[str, ...]:
        """Return required capabilities that cannot be resolved locally."""
        return tuple(capability.name for capability in self.capabilities if capability.required and self._resolve(capability) is None)
