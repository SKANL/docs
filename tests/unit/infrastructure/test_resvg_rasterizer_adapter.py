# tests/unit/infrastructure/test_resvg_rasterizer_adapter.py
"""`SvgRasterizerPort` implementation for `resvg`: fixed subprocess arg list
(Threat Matrix "Subprocess arg composition" -- never `shell=True`, paths
passed as explicit args)."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from docs.infrastructure.visuals.resvg_rasterizer_adapter import ResvgRasterizerAdapter


class _FakeToolResolver:
    def __init__(self, resvg: str | None) -> None:
        self._resvg = resvg

    def resolve_resvg(self, paths):
        return self._resvg


def _run_writing_png(png_bytes: bytes):
    def _run(args, **kwargs):
        Path(args[2]).write_bytes(png_bytes)
        return mock.Mock(returncode=0)

    return _run


def test_rasterize_never_uses_shell(tmp_path):
    svg_path = tmp_path / "diagram.svg"
    svg_path.write_text("<svg></svg>", encoding="utf-8")
    png_path = tmp_path / "diagram.png"
    font_dir = tmp_path / "fonts"
    adapter = ResvgRasterizerAdapter(_FakeToolResolver("/usr/bin/resvg"), font_dir=font_dir)

    with mock.patch("subprocess.run", side_effect=_run_writing_png(b"fake-png")) as mock_run:
        adapter.rasterize(svg_path, png_path)

    mock_run.assert_called_once()
    call_args, call_kwargs = mock_run.call_args
    assert isinstance(call_args[0], list)
    assert call_kwargs.get("shell") is not True
    assert call_args[0] == [
        "/usr/bin/resvg",
        str(svg_path),
        str(png_path),
        "--use-fonts-dir",
        str(font_dir),
    ]
    assert png_path.read_bytes() == b"fake-png"


def test_rasterize_without_font_dir_omits_fonts_dir_flag(tmp_path):
    svg_path = tmp_path / "diagram.svg"
    svg_path.write_text("<svg></svg>", encoding="utf-8")
    png_path = tmp_path / "diagram.png"
    adapter = ResvgRasterizerAdapter(_FakeToolResolver("/usr/bin/resvg"))

    with mock.patch("subprocess.run", side_effect=_run_writing_png(b"fake-png")) as mock_run:
        adapter.rasterize(svg_path, png_path)

    call_args, _ = mock_run.call_args
    assert call_args[0] == ["/usr/bin/resvg", str(svg_path), str(png_path)]


def test_missing_resvg_raises_runtime_error_with_guidance(tmp_path):
    svg_path = tmp_path / "diagram.svg"
    svg_path.write_text("<svg></svg>", encoding="utf-8")
    png_path = tmp_path / "diagram.png"
    adapter = ResvgRasterizerAdapter(_FakeToolResolver(None))

    with pytest.raises(RuntimeError, match="resvg"):
        adapter.rasterize(svg_path, png_path)
