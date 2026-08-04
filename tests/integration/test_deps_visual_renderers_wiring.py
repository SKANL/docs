# tests/integration/test_deps_visual_renderers_wiring.py
"""Composition-root wiring for the on-demand-visual-generation renderers
(design.md: `visual_renderers` registry keyed by `type`, mirrors
`ingest_handlers` keyed by `kind`). Slice 2 wires `"chart"`; Slice 3 extends
this file with `"mermaid"`."""
from pathlib import Path

from docs.cli._shared import Deps
from docs.domain.workspace import Workspace
from docs.infrastructure.visuals.chart_svg_renderer import ChartSvgRenderer
from docs.infrastructure.visuals.mermaid_svg_renderer import MermaidSvgRenderer


def _deps(tmp_path: Path) -> Deps:
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    return Deps(workspace)


def test_deps_wires_a_chart_renderer_when_matplotlib_available(tmp_path: Path):
    # matplotlib is a real declared dependency (pyproject.toml), so the
    # guarded import in `Deps.__init__` must succeed here and register a
    # real `ChartSvgRenderer` under `"chart"` -- never absent.
    deps = _deps(tmp_path)
    assert isinstance(deps.visual_renderers["chart"], ChartSvgRenderer)
    assert deps.visual_renderers["chart"].type == "chart"


def test_deps_wires_a_mermaid_renderer_regardless_of_mmdc_availability(tmp_path: Path):
    # `mmdc` is an OPTIONAL PATH toolchain -- its absence must never keep
    # `MermaidSvgRenderer` out of the registry (resolution is deferred to
    # `render()`, per design.md's fail-open contract).
    deps = _deps(tmp_path)
    assert isinstance(deps.visual_renderers["mermaid"], MermaidSvgRenderer)
    assert deps.visual_renderers["mermaid"].type == "mermaid"
