# tests/integration/test_html_determinism.py
"""Determinism proof for `HtmlRendererAdapter` (design.md item C-html): same
sections, unchanged, must produce byte-identical `.html` across independent
runs — the reproducibility guarantee this harness makes for every renderer
(AGENTS.md §5), same as `test_docx_zip_determinism.py` proves for DOCX."""
from __future__ import annotations

import shutil
import time as time_module

import pytest

from docs.application.html_render import HtmlRendererAdapter
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter

pytestmark = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")


def _config(tmp_path, sections_dir):
    return {
        "sections": [{"id": "resumen", "order": 1}, {"id": "anexos", "order": 2}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(tmp_path / "draft")},
    }


def _write_sections(sections_dir):
    sections_dir.mkdir(parents=True, exist_ok=True)
    (sections_dir / "001-resumen.md").write_text(
        "# Resumen\n\n[[figure:organigrama]] Organigrama del equipo.\n", encoding="utf-8"
    )
    (sections_dir / "002-anexos.md").write_text(
        "# Anexos\n\nConsulte [[ref:organigrama]] para más detalle.\n", encoding="utf-8"
    )


def test_build_produces_byte_identical_html_across_two_independent_runs(tmp_path):
    sections_dir = tmp_path / "sections"
    _write_sections(sections_dir)
    service = HtmlRendererAdapter(SystemToolResolverAdapter())

    first = service.build("doc-1", _config(tmp_path, sections_dir), output=tmp_path / "first.html")
    second = service.build("doc-1", _config(tmp_path, sections_dir), output=tmp_path / "second.html")

    assert first.read_bytes() == second.read_bytes()


def test_build_is_byte_identical_across_a_real_wall_clock_gap(tmp_path):
    # pandoc's wall clock is read inside a separate subprocess, so (like
    # `test_render_pandoc_output_is_byte_identical_across_a_real_wall_clock_gap`
    # for docx) this uses a real sleep rather than monkeypatching `time.time`.
    sections_dir = tmp_path / "sections"
    _write_sections(sections_dir)
    service = HtmlRendererAdapter(SystemToolResolverAdapter())

    first = service.build("doc-1", _config(tmp_path, sections_dir), output=tmp_path / "first.html")
    time_module.sleep(2.1)
    second = service.build("doc-1", _config(tmp_path, sections_dir), output=tmp_path / "second.html")

    assert first.read_bytes() == second.read_bytes()
