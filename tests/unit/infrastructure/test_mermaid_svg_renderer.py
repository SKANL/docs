# tests/unit/infrastructure/test_mermaid_svg_renderer.py
"""`VisualRendererPort` implementation for `type = "mermaid"`: `mmdc`
subprocess, source written to a temp file (Threat Matrix "Subprocess arg
composition" -- never a shell arg, never `shell=True`)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest import mock

import pytest

from docs.domain.ports.visual_renderer_port import VisualSpec
from docs.domain.svg_normalize import normalize_svg
from docs.infrastructure.visuals.mermaid_svg_renderer import MermaidSvgRenderer


class _FakeToolResolver:
    def __init__(self, mmdc: str | None) -> None:
        self._mmdc = mmdc

    def resolve_mmdc(self, paths):
        return self._mmdc


def _run_writing_svg(svg_text: str, captured: dict | None = None):
    def _run(args, **kwargs):
        if captured is not None:
            captured["args"] = args
            captured["kwargs"] = kwargs
            captured["mmd_text"] = Path(args[2]).read_text(encoding="utf-8")
        Path(args[4]).write_text(svg_text, encoding="utf-8")
        return mock.Mock(returncode=0)

    return _run


def test_source_with_shell_metacharacters_never_reaches_a_shell(tmp_path):
    malicious_source = 'graph TD; A-->B; $(rm -rf /) `echo pwned`; "; rm -rf / #'
    spec = VisualSpec(label="fig", type="mermaid", source=malicious_source)
    renderer = MermaidSvgRenderer(_FakeToolResolver("/usr/bin/mmdc"), scratch_root=tmp_path)

    captured: dict = {}
    with mock.patch("subprocess.run", side_effect=_run_writing_svg("<svg></svg>", captured)) as mock_run:
        svg = renderer.render(spec)

    mock_run.assert_called_once()
    call_args, call_kwargs = mock_run.call_args
    # (a) called with a list, never a string; shell never True.
    assert isinstance(call_args[0], list)
    assert call_kwargs.get("shell") is not True
    # (b) source written to a temp file, passed as a file path -- the
    # metacharacters live only inside that file's bytes, never in argv or a
    # shell string.
    assert captured["mmd_text"] == malicious_source
    assert all(malicious_source not in str(arg) for arg in call_args[0])
    assert "<svg" in svg


def test_render_missing_mmdc_raises_runtime_error_with_guidance(tmp_path):
    spec = VisualSpec(label="fig", type="mermaid", source="graph TD; A-->B;")
    renderer = MermaidSvgRenderer(_FakeToolResolver(None), scratch_root=tmp_path)

    with pytest.raises(RuntimeError, match="mmdc"):
        renderer.render(spec)


def test_render_returns_svg_text_from_mmdc_output(tmp_path):
    spec = VisualSpec(label="fig", type="mermaid", source="graph TD; A-->B;")
    renderer = MermaidSvgRenderer(_FakeToolResolver("/usr/bin/mmdc"), scratch_root=tmp_path)
    fixed_svg = '<svg><rect id="r1"/></svg>'

    with mock.patch("subprocess.run", side_effect=_run_writing_svg(fixed_svg)):
        svg = renderer.render(spec)

    assert svg == fixed_svg


def test_render_plus_normalize_svg_is_byte_identical_across_two_runs(tmp_path):
    spec = VisualSpec(label="fig", type="mermaid", source="graph TD; A-->B;")
    renderer = MermaidSvgRenderer(_FakeToolResolver("/usr/bin/mmdc"), scratch_root=tmp_path)
    fixed_svg = '<svg><g id="clip1"><rect id="r1"/></g><!-- generated 2026 --></svg>'

    with mock.patch("subprocess.run", side_effect=_run_writing_svg(fixed_svg)):
        first = normalize_svg(renderer.render(spec))
    with mock.patch("subprocess.run", side_effect=_run_writing_svg(fixed_svg)):
        second = normalize_svg(renderer.render(spec))

    assert hashlib.sha256(first.encode()).hexdigest() == hashlib.sha256(second.encode()).hexdigest()
