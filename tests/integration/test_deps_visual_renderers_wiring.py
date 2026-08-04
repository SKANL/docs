# tests/integration/test_deps_visual_renderers_wiring.py
"""Composition-root wiring for the on-demand-visual-generation renderers
(design.md: `visual_renderers` registry keyed by `type`, mirrors
`ingest_handlers` keyed by `kind`). Slice 2 wires `"chart"`; Slice 3 extends
this file with `"mermaid"`."""
from pathlib import Path

from docs.application.generate_visuals import GenerateVisualsService
from docs.cli._shared import Deps
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.python_docx_image_metadata_adapter import PythonDocxImageMetadataAdapter
from docs.infrastructure.visuals.chart_svg_renderer import ChartSvgRenderer
from docs.infrastructure.visuals.mermaid_svg_renderer import MermaidSvgRenderer
from docs.infrastructure.visuals.resvg_rasterizer_adapter import ResvgRasterizerAdapter


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


def test_deps_wires_a_resvg_rasterizer_regardless_of_resvg_availability(tmp_path: Path):
    # `resvg` is an OPTIONAL PATH toolchain -- its absence must never keep
    # `ResvgRasterizerAdapter` unwired (resolution is deferred to
    # `rasterize()`, per design.md's fail-open contract).
    deps = _deps(tmp_path)
    assert isinstance(deps.svg_rasterizer, ResvgRasterizerAdapter)


def test_deps_wires_a_generate_visuals_service_with_the_chart_and_mermaid_registry(tmp_path: Path):
    # Slice 5b: composition-root wiring -- `Deps().pipeline.generate_visuals_service`
    # reuses the SAME `visual_renderers`/`svg_rasterizer` registries built
    # above (no second registry instantiated) and the EXISTING
    # `PythonDocxImageMetadataAdapter` for dims (no new dims port).
    deps = _deps(tmp_path)
    service = deps.pipeline.generate_visuals_service
    assert isinstance(service, GenerateVisualsService)
    assert service.visual_renderers is not deps.visual_renderers  # defensive copy (GenerateVisualsService.__init__)
    assert service.visual_renderers.keys() == {"chart", "mermaid"}
    assert service.visual_renderers["chart"] is deps.visual_renderers["chart"]
    assert service.visual_renderers["mermaid"] is deps.visual_renderers["mermaid"]
    assert service.svg_rasterizer is deps.svg_rasterizer
    assert isinstance(service.image_metadata, PythonDocxImageMetadataAdapter)


def test_deps_pipeline_service_has_the_same_generate_visuals_service_instance(tmp_path: Path):
    deps = _deps(tmp_path)
    assert deps.pipeline.generate_visuals_service is deps.generate_visuals_service
