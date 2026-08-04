# tests/unit/application/test_docx_assembly_ignores_sibling_svg.py
"""Characterization guard (tasks.md Slice 6, task 6.2): `docx_assembly.py`
is UNTOUCHED by the Slice-6 HTML sibling-SVG swap
(`html_render.py:_prefer_sibling_svg`). The SAME bound figure -- a `.png`
with a same-stem sibling `.svg` both present on disk -- must still embed the
PNG when built to docx (pandoc#9195 blocker on SVG-in-docx locks this
contract from regressing). If this fails, Slice 6 leaked into the docx
path."""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from docx import Document

from docs.application.asset import AssetService
from docs.application.docx_assembly import DocxRendererAdapter
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository


def _write_json(path: Path, payload: dict) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _solid_png(width: int, height: int) -> bytes:
    """Same minimal, genuinely-parseable RGB PNG construction as
    `test_docx_assembly_service.py::_solid_png` -- pandoc must be able to
    embed a real image for the media-entry assertion below."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = b"".join(b"\x00" + bytes([180, 180, 180] * width) for _ in range(height))
    idat = zlib.compress(raw)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _pandoc_styled_docx(tmp_path: Path, text: str, name: str) -> Path:
    seed = tmp_path / f"_seed_{name}.md"
    seed.write_text(f"{text}\n", encoding="utf-8")
    target = tmp_path / name
    subprocess.run([shutil.which("pandoc"), str(seed), "-o", str(target)], check=True)
    return target


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_docx_always_embeds_png_even_with_sibling_svg(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    service = DocxRendererAdapter(PythonDocxAssemblyAdapter(), asset_service, SystemToolResolverAdapter())

    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    draft_dir = tmp_path / "draft"
    (sections_dir / "001-resumen.md").write_text(
        "# Resumen\n\n[[figure:organigrama]] Organigrama del equipo.\n", encoding="utf-8"
    )
    assets_dir = workspace.assets_dir("doc-1")
    figures_dir = assets_dir / "figures"
    figures_dir.mkdir(parents=True)
    png_bytes = _solid_png(150, 100)
    (figures_dir / "visual-abc12345.png").write_bytes(png_bytes)
    # Same-stem sibling `.svg` present too -- exactly the shape a
    # generate-visuals entry produces (application/generate_visuals.py).
    (figures_dir / "visual-abc12345.svg").write_text("<svg></svg>", encoding="utf-8")
    _write_json(
        sections_dir / "figure-catalog.json",
        {
            "figures": [
                {
                    "id": "visual-abc12345",
                    "sha256": "0" * 64,
                    "width_px": 150,
                    "height_px": 100,
                    "origin_relative_path": "assets/figures/visual-abc12345.png",
                    "caption": "Organigrama del equipo",
                    "source_role": "",
                    "origin_kind": "generated",
                }
            ]
        },
    )
    _write_json(
        sections_dir / "figure-bindings.json",
        {"schema": 1, "bindings": {"organigrama": "visual-abc12345"}},
    )
    template = _pandoc_styled_docx(tmp_path, "Plantilla.", "template.docx")

    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {
            "sections_dir": str(sections_dir),
            "output_draft_dir": str(draft_dir),
            "template_docx": str(template),
            "assets_dir": str(assets_dir),
        },
    }

    output = service.build("doc-1", config)

    with zipfile.ZipFile(output) as archive:
        media_entries = [name for name in archive.namelist() if name.startswith("word/media/")]
        media_bytes = [archive.read(name) for name in media_entries]

    assert len(media_entries) == 1
    assert png_bytes in media_bytes  # the PNG, not the SVG, was embedded

    document = Document(str(output))
    texts = [p.text for p in document.paragraphs]
    assert any("Organigrama del equipo" in t for t in texts)
