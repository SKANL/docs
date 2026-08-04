# tests/integration/test_generate_visuals_e2e.py
"""End-to-end proof of the whole on-demand-visual-generation feature
(tasks.md Slice 6, task 6.3): `visual-specs.json` -> `GenerateVisualsService`
(render -> normalize -> rasterize -> catalog/bind) -> assemble, asserting
docx embeds the generated PNG and HTML embeds the sibling SVG
(application/html_render.py:_prefer_sibling_svg, Slice 6). A hermetic
`_FakeSvgRasterizer` (writes a real, tiny, deterministic PNG) lets the
chart-only path run on hosts without resvg installed -- chart rendering
itself needs only matplotlib (already a hard pyproject dependency). The
mermaid+chart byte-identity rebuild needs the REAL `mmdc`/`resvg` toolchain
and is `@pytest.mark.skipif`-skipped when either is absent from PATH."""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from docs.application.asset import AssetService
from docs.application.docx_assembly import DocxRendererAdapter
from docs.application.generate_visuals import GenerateVisualsService
from docs.application.html_render import HtmlRendererAdapter
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
from docs.infrastructure.docx.python_docx_image_metadata_adapter import PythonDocxImageMetadataAdapter
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.visuals.chart_svg_renderer import ChartSvgRenderer

_HAS_PANDOC = shutil.which("pandoc") is not None
_HAS_MMDC = shutil.which("mmdc") is not None
_HAS_RESVG = shutil.which("resvg") is not None


class _FakeSvgRasterizer:
    """`SvgRasterizerPort` test double: writes a real, tiny, deterministic
    PNG regardless of the SVG content -- lets the chart-only E2E run
    hermetically on a host without resvg installed (tasks.md 6.3: "chart
    needs only matplotlib"). Same size/color every call, so a byte-identity
    rebuild assertion over it would still hold (not exercised by the
    chart-only test below, which only runs once)."""

    def rasterize(self, svg_path: Path, png_path: Path) -> None:
        Image.new("RGB", (64, 32), color=(10, 20, 30)).save(png_path, format="PNG")


def _chart_spec(label: str) -> dict:
    return {
        "label": label,
        "type": "chart",
        "source": json.dumps(
            {"kind": "bar", "labels": ["Q1", "Q2"], "series": [{"label": "Revenue", "values": [1, 2]}]}
        ),
        "caption": "Revenue chart",
    }


def _build_config(sections_dir: Path, assets_dir: Path, draft_dir: Path) -> dict:
    return {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {
            "sections_dir": str(sections_dir),
            "assets_dir": str(assets_dir),
            "output_draft_dir": str(draft_dir),
        },
    }


def _write_section_with_figure(sections_dir: Path, label: str) -> None:
    sections_dir.mkdir(parents=True, exist_ok=True)
    (sections_dir / "001-resumen.md").write_text(
        f"# Resumen\n\n[[figure:{label}]] Descripcion del visual.\n", encoding="utf-8"
    )


@pytest.mark.skipif(not _HAS_PANDOC, reason="pandoc not installed")
def test_chart_only_pipeline_e2e_docx_png_html_svg(tmp_path):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    draft_dir = tmp_path / "draft"
    _write_section_with_figure(sections_dir, "revenue")
    (sections_dir / "visual-specs.json").write_text(json.dumps([_chart_spec("revenue")]), encoding="utf-8")

    generate_service = GenerateVisualsService(
        {"chart": ChartSvgRenderer()}, _FakeSvgRasterizer(), image_metadata=PythonDocxImageMetadataAdapter()
    )
    result = generate_service.generate(sections_dir, assets_dir)
    assert result.generated == 1
    assert result.skipped == 0

    figures_dir = assets_dir / "figures"
    png_path = next(figures_dir.glob("*.png"))
    svg_path = next(figures_dir.glob("*.svg"))
    assert png_path.stem == svg_path.stem  # shared stem (design.md: sibling identity)

    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    tool_resolver = SystemToolResolverAdapter()
    docx_renderer = DocxRendererAdapter(PythonDocxAssemblyAdapter(), asset_service, tool_resolver)
    html_renderer = HtmlRendererAdapter(tool_resolver)
    config = _build_config(sections_dir, assets_dir, draft_dir)

    docx_path = docx_renderer.build("doc1", config)
    html_path = html_renderer.build("doc1", config)

    with zipfile.ZipFile(docx_path) as archive:
        media_bytes = [
            archive.read(name) for name in archive.namelist() if name.startswith("word/media/")
        ]
    assert png_path.read_bytes() in media_bytes  # docx embeds the PNG

    html_text = html_path.read_text(encoding="utf-8")
    assert "data:image/svg" in html_text  # html embeds the SVG (--embed-resources inlines it)


@pytest.mark.skipif(not (_HAS_MMDC and _HAS_RESVG), reason="mmdc and/or resvg not installed")
def test_mermaid_and_chart_pipeline_e2e_byte_identical(tmp_path):
    from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter as _Resolver
    from docs.infrastructure.visuals.mermaid_svg_renderer import MermaidSvgRenderer
    from docs.infrastructure.visuals.resvg_rasterizer_adapter import ResvgRasterizerAdapter

    tool_resolver = _Resolver()
    renderers = {"chart": ChartSvgRenderer(), "mermaid": MermaidSvgRenderer(tool_resolver)}
    specs = [
        _chart_spec("revenue"),
        {"label": "flow", "type": "mermaid", "source": "graph TD; A-->B;", "caption": "Flow diagram"},
    ]

    def run_once(root: Path) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, bytes]]:
        sections_dir = root / "sections"
        assets_dir = root / "assets"
        draft_dir = root / "draft"
        _write_section_with_figure(sections_dir, "revenue")
        (sections_dir / "001-resumen.md").write_text(
            "# Resumen\n\n[[figure:revenue]] Ingresos.\n\n[[figure:flow]] Flujo.\n", encoding="utf-8"
        )
        (sections_dir / "visual-specs.json").write_text(json.dumps(specs), encoding="utf-8")

        generate_service = GenerateVisualsService(
            renderers, ResvgRasterizerAdapter(tool_resolver), image_metadata=PythonDocxImageMetadataAdapter()
        )
        result = generate_service.generate(sections_dir, assets_dir)
        assert result.skipped == 0

        workspace = Workspace(documents_dir=root / "documents", templates_dir=root / "templates")
        asset_service = AssetService(FilesystemAssetRepository(), workspace)
        docx_renderer = DocxRendererAdapter(PythonDocxAssemblyAdapter(), asset_service, tool_resolver)
        html_renderer = HtmlRendererAdapter(tool_resolver)
        config = _build_config(sections_dir, assets_dir, draft_dir)

        docx_path = docx_renderer.build("doc1", config)
        html_path = html_renderer.build("doc1", config)

        generated_bytes = {p.name: p.read_bytes() for p in sorted((assets_dir / "figures").iterdir())}
        catalog_bytes = (sections_dir / "figure-catalog.json").read_bytes()
        bindings_bytes = (sections_dir / "figure-bindings.json").read_bytes()
        artifacts = {
            "figure-catalog.json": catalog_bytes,
            "figure-bindings.json": bindings_bytes,
            **generated_bytes,
        }
        return artifacts, {"docx": docx_path.read_bytes()}, {"html": html_path.read_bytes()}

    first_artifacts, first_docx, first_html = run_once(tmp_path / "run1")
    second_artifacts, second_docx, second_html = run_once(tmp_path / "run2")

    assert first_artifacts and first_artifacts == second_artifacts
    assert first_docx == second_docx
    assert first_html == second_html
