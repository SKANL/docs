from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.tool_capability import (
    CapabilityDetection,
    CapabilityPolicyState,
    ToolCapability,
    ToolCapabilityRegistry,
)
from docs.infrastructure.tools.tool_capability_detector_adapter import NativeToolCapabilityDetector


@dataclass
class FakeDetector:
    detections: dict[str, CapabilityDetection]
    calls: list[str]

    def detect(self, capability: ToolCapability) -> CapabilityDetection:
        self.calls.append(capability.name)
        return self.detections[capability.name]


def test_native_detector_contains_missing_dotted_module_failure() -> None:
    detection = NativeToolCapabilityDetector().detect(
        ToolCapability("missing", "", module="missing_parent.missing_module")
    )

    assert detection == CapabilityDetection.unavailable(
        "Python module not found: missing_parent.missing_module"
    )


def test_missing_dotted_module_remains_policy_aware() -> None:
    registry = ToolCapabilityRegistry(
        (
            ToolCapability(
                "missing",
                "",
                module="missing_parent.missing_module",
                policy=CapabilityPolicyState.required,
            ),
        ),
        NativeToolCapabilityDetector(),
    )

    evaluation = registry.evaluate(PipelinePolicy(PipelineMode.strict))

    assert evaluation.blocking is True
    assert evaluation.errors == ("required capability unavailable: missing",)


def test_registry_uses_injected_detector_lazily_and_lists_capabilities_deterministically() -> None:
    detector = FakeDetector(
        {
            "zeta": CapabilityDetection.unavailable("not installed"),
            "pandoc": CapabilityDetection.available_at("/bin/pandoc", version="3.1"),
        },
        [],
    )
    registry = ToolCapabilityRegistry(
        (
            ToolCapability("zeta", "zeta"),
            ToolCapability("pandoc", "pandoc", policy=CapabilityPolicyState.required),
        ),
        detector,
    )

    assert detector.calls == []
    assert registry.report() == {
        "pandoc": {"available": True, "path": "/bin/pandoc"},
        "zeta": {"available": False, "path": None},
    }
    assert detector.calls == ["pandoc", "zeta"]
    assert registry.diagnostics() == {
        "pandoc": {
            "available": True,
            "path": "/bin/pandoc",
            "required": True,
            "policy": "required",
            "kind": "executable",
            "version": "3.1",
            "diagnostic": None,
            "requirement": None,
            "degradation": None,
        },
        "zeta": {
            "available": False,
            "path": None,
            "required": False,
            "policy": "optional",
            "kind": "executable",
            "version": None,
            "diagnostic": "not installed",
            "requirement": None,
            "degradation": None,
        },
    }
    assert detector.calls == ["pandoc", "zeta"]


@pytest.mark.parametrize(
    ("mode", "blocking", "warnings", "errors"),
    (
        (PipelineMode.draft, False, ("optional capability unavailable: resvg",), ()),
        (PipelineMode.strict, True, (), ("optional capability unavailable: resvg",)),
        (PipelineMode.release, True, (), ("optional capability unavailable: resvg",)),
    ),
)
def test_optional_capability_policy_degrades_only_in_draft(
    mode: PipelineMode,
    blocking: bool,
    warnings: tuple[str, ...],
    errors: tuple[str, ...],
) -> None:
    registry = ToolCapabilityRegistry(
        (ToolCapability("resvg", "resvg"),),
        FakeDetector({"resvg": CapabilityDetection.unavailable("missing binary")}, []),
    )

    evaluation = registry.evaluate(PipelinePolicy(mode))

    assert evaluation.blocking is blocking
    assert evaluation.warnings == warnings
    assert evaluation.errors == errors
    assert evaluation.to_json() == json.dumps(
        {"blocking": blocking, "errors": list(errors), "mode": mode.value, "warnings": list(warnings)},
        separators=(",", ":"),
        sort_keys=True,
    )

