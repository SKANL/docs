# tests/integration/test_mermaid_svg_renderer_integration.py
"""Real-toolchain integration check of `MermaidSvgRenderer` (same code path
as `tests/unit/infrastructure/test_mermaid_svg_renderer.py`, exercised
against an actual `mmdc` installation). Skips cleanly when `mmdc` is absent
from PATH (mirrors the `pandoc`/`java`/`libreoffice` skipif precedent)."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from docs.domain.ports.visual_renderer_port import VisualSpec
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.visuals.mermaid_svg_renderer import MermaidSvgRenderer

_HAS_MMDC = shutil.which("mmdc") is not None


@pytest.mark.skipif(not _HAS_MMDC, reason="mmdc not installed")
def test_render_produces_svg_via_real_mmdc(tmp_path):
    spec = VisualSpec(label="fig", type="mermaid", source="graph TD;\nA-->B;\n")
    renderer = MermaidSvgRenderer(SystemToolResolverAdapter(), scratch_root=tmp_path)

    svg = renderer.render(spec)

    assert "<svg" in svg


@pytest.mark.skipif(not _HAS_MMDC, reason="mmdc not installed")
def test_render_invalid_mermaid_syntax_raises_with_cause(tmp_path):
    spec = VisualSpec(label="fig", type="mermaid", source="this is not valid mermaid syntax {{{")
    renderer = MermaidSvgRenderer(SystemToolResolverAdapter(), scratch_root=tmp_path)

    # The class docstring promises "a clean, catchable error so the
    # generate-visuals stage can WARN+skip it". It raised a raw
    # `CalledProcessError` instead, whose message is a Windows path dump --
    # and mmdc's actual diagnostic went to the inherited stderr, so the
    # stage's `WARN: {exc}` told the author nothing about their diagram.
    with pytest.raises(RuntimeError) as excinfo:
        renderer.render(spec)

    assert "mmdc" in str(excinfo.value)
    assert "UnknownDiagramError" in str(excinfo.value), "el diagnóstico de mermaid debe llegar al autor"
    assert isinstance(excinfo.value.__cause__, subprocess.CalledProcessError)
