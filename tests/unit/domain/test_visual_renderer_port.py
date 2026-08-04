# tests/unit/domain/test_visual_renderer_port.py
"""On-demand visual generation (design.md "VisualRendererPort registry keyed
by visual `type`"). `VisualSpec` is the agent-authored declarative input;
`VisualRendererPort` is the format-agnostic renderer contract each concrete
adapter (chart/mermaid) implements -- pure domain shape, no I/O."""
from __future__ import annotations

import dataclasses
from typing import Protocol, runtime_checkable

import pytest

from docs.domain.ports.visual_renderer_port import VisualRendererPort, VisualSpec


def test_visual_spec_constructs_with_required_fields():
    spec = VisualSpec(label="arch-diagram", type="mermaid", source="graph TD; A-->B")
    assert spec.label == "arch-diagram"
    assert spec.type == "mermaid"
    assert spec.source == "graph TD; A-->B"


def test_visual_spec_caption_defaults_to_empty_string():
    spec = VisualSpec(label="l", type="chart", source="{}")
    assert spec.caption == ""


def test_visual_spec_is_frozen():
    spec = VisualSpec(label="l", type="chart", source="{}")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.label = "other"  # type: ignore[misc]


def test_visual_renderer_port_is_a_protocol():
    assert issubclass(VisualRendererPort, Protocol)  # type: ignore[arg-type]


def test_visual_renderer_port_declares_type_and_render():
    @runtime_checkable
    class _Checkable(VisualRendererPort, Protocol):  # type: ignore[misc]
        ...

    class FakeRenderer:
        type = "fake"

        def render(self, spec: VisualSpec) -> str:
            return "<svg></svg>"

    assert isinstance(FakeRenderer(), _Checkable)
