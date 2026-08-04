# tests/unit/application/test_generate_visuals_service.py
"""`GenerateVisualsService` (design.md Data Flow; tasks.md S5 5.1-5.7): reads
agent-authored `sections/visual-specs.json`, dispatches each entry to its
registered `VisualRendererPort` by `type`, normalizes+rasterizes the result
into a sibling `.svg`/`.png` pair, and merges the outcome into
`figure-catalog.json` (`origin_kind="generated"`) + auto-binds into
`figure-bindings.json` (no-clobber). Every per-visual failure is WARN+skip
(capsys-checked), never a raised exception out of `generate()`. Uses FAKE
ports throughout -- no real mmdc/resvg/matplotlib -- so this suite is
hermetic and fast."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from docs.application.generate_visuals import GenerateVisualsService
from docs.domain.ingest_naming import sha256_hex
from docs.domain.ports.visual_renderer_port import VisualSpec
from docs.domain.svg_normalize import normalize_svg


@dataclass
class FakeRenderer:
    type: str
    svg: str = "<svg><rect/></svg>"
    exc: Exception | None = None
    calls: list[VisualSpec] = field(default_factory=list)

    def render(self, spec: VisualSpec) -> str:
        self.calls.append(spec)
        if self.exc is not None:
            raise self.exc
        return self.svg


class FakeRasterizer:
    """Deterministic, content-derived fake PNG -- differs per distinct SVG
    input, so distinct visuals produce distinct catalog ids (mirrors resvg's
    real determinism contract without a real toolchain)."""

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls: list[tuple[Path, Path]] = []

    def rasterize(self, svg_path: Path, png_path: Path) -> None:
        self.calls.append((svg_path, png_path))
        if self.exc is not None:
            raise self.exc
        Path(png_path).write_bytes(b"PNG:" + Path(svg_path).read_bytes())


class FakeImageMetadata:
    def __init__(self, dims: tuple[int, int] | None = (300, 200)) -> None:
        self.dims = dims

    def read_dimensions(self, path: Path) -> tuple[int, int] | None:
        return self.dims


def _write_specs(sections_dir: Path, entries: list[dict]) -> None:
    sections_dir.mkdir(parents=True, exist_ok=True)
    (sections_dir / "visual-specs.json").write_text(json.dumps(entries), encoding="utf-8")


def _write_catalog(sections_dir: Path, figures: list[dict]) -> None:
    sections_dir.mkdir(parents=True, exist_ok=True)
    (sections_dir / "figure-catalog.json").write_text(json.dumps({"figures": figures}), encoding="utf-8")


def _write_bindings(sections_dir: Path, bindings: dict[str, str]) -> None:
    sections_dir.mkdir(parents=True, exist_ok=True)
    (sections_dir / "figure-bindings.json").write_text(
        json.dumps({"bindings": bindings}), encoding="utf-8"
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _service(
    renderers: dict[str, FakeRenderer], rasterizer: FakeRasterizer, dims: tuple[int, int] | None = (300, 200)
) -> GenerateVisualsService:
    return GenerateVisualsService(
        visual_renderers=renderers,
        svg_rasterizer=rasterizer,
        image_metadata=FakeImageMetadata(dims),
    )


# --- 5.1 registry dispatch by type ---------------------------------------


def test_registry_dispatch_by_type(tmp_path):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_specs(
        sections_dir,
        [
            {"label": "alpha", "type": "chart", "source": "s1", "caption": "Alpha"},
            {"label": "beta", "type": "mermaid", "source": "s2", "caption": "Beta"},
        ],
    )
    chart_renderer = FakeRenderer(type="chart", svg='<svg id="a"><rect/></svg>')
    mermaid_renderer = FakeRenderer(type="mermaid", svg='<svg id="b"><circle/></svg>')
    service = _service({"chart": chart_renderer, "mermaid": mermaid_renderer}, FakeRasterizer())

    result = service.generate(sections_dir, assets_dir)

    assert len(chart_renderer.calls) == 1
    assert chart_renderer.calls[0].label == "alpha"
    assert len(mermaid_renderer.calls) == 1
    assert mermaid_renderer.calls[0].label == "beta"
    assert result.generated == 2
    assert result.skipped == 0


def test_unregistered_type_warns_and_skips(tmp_path, capsys):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_specs(
        sections_dir,
        [
            {"label": "unknown-visual", "type": "plantuml", "source": "s1"},
            {"label": "known-visual", "type": "chart", "source": "s2"},
        ],
    )
    chart_renderer = FakeRenderer(type="chart", svg="<svg><rect/></svg>")
    service = _service({"chart": chart_renderer}, FakeRasterizer())

    result = service.generate(sections_dir, assets_dir)

    assert len(chart_renderer.calls) == 1  # only the registered-type entry dispatched
    assert result.generated == 1
    assert result.skipped == 1
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "plantuml" in captured.err


# --- 5.2 missing visual-specs.json is a no-op ------------------------------


def test_missing_visual_specs_file_is_noop(tmp_path):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    assets_dir = tmp_path / "assets"
    _write_catalog(sections_dir, [{"id": "fig-existing1", "sha256": "0" * 64, "width_px": 10,
                                    "height_px": 10, "origin_relative_path": "assets/figures/x.png",
                                    "caption": "", "source_role": "", "origin_kind": "standalone"}])
    _write_bindings(sections_dir, {"existing-label": "fig-existing1"})
    catalog_before = (sections_dir / "figure-catalog.json").read_text(encoding="utf-8")
    bindings_before = (sections_dir / "figure-bindings.json").read_text(encoding="utf-8")

    service = _service({}, FakeRasterizer())
    result = service.generate(sections_dir, assets_dir)

    assert result.generated == 0
    assert result.skipped == 0
    assert (sections_dir / "figure-catalog.json").read_text(encoding="utf-8") == catalog_before
    assert (sections_dir / "figure-bindings.json").read_text(encoding="utf-8") == bindings_before


# --- 5.3 malformed entry warns naming missing field, others still process -


def test_malformed_entry_warns_naming_missing_field_others_still_process(tmp_path, capsys):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_specs(
        sections_dir,
        [
            {"label": "missing-source", "type": "chart"},  # no `source`
            {"label": "well-formed", "type": "chart", "source": "s1", "caption": "OK"},
        ],
    )
    chart_renderer = FakeRenderer(type="chart", svg="<svg><rect/></svg>")
    service = _service({"chart": chart_renderer}, FakeRasterizer())

    result = service.generate(sections_dir, assets_dir)

    assert len(chart_renderer.calls) == 1
    assert chart_renderer.calls[0].label == "well-formed"
    assert result.generated == 1
    assert result.skipped == 1
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "source" in captured.err


# --- 5.4 well-formed entry writes sibling svg+png with shared stem --------


def test_well_formed_entry_writes_sibling_svg_and_png_with_shared_stem(tmp_path):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    raw_svg = '<svg id="abc"><rect/></svg>'
    _write_specs(sections_dir, [{"label": "arch", "type": "chart", "source": "s1", "caption": "Arch"}])
    service = _service({"chart": FakeRenderer(type="chart", svg=raw_svg)}, FakeRasterizer())

    service.generate(sections_dir, assets_dir)

    expected_stem = f"visual-{sha256_hex(normalize_svg(raw_svg).encode('utf-8'))[:8]}"
    svg_path = assets_dir / "figures" / f"{expected_stem}.svg"
    png_path = assets_dir / "figures" / f"{expected_stem}.png"
    assert svg_path.exists()
    assert png_path.exists()
    assert svg_path.read_text(encoding="utf-8") == normalize_svg(raw_svg)

    catalog = _read_json(sections_dir / "figure-catalog.json")
    assert len(catalog["figures"]) == 1
    row = catalog["figures"][0]
    assert row["origin_kind"] == "generated"
    assert row["width_px"] == 300
    assert row["height_px"] == 200
    assert row["sha256"] == sha256_hex(png_path.read_bytes())
    assert row["id"] == f"fig-{row['sha256'][:8]}"
    assert row["origin_relative_path"] == f"assets/figures/{expected_stem}.png"


# --- 5.5 generated entries merged into existing catalog and written -------


def test_generated_entries_merged_into_existing_catalog_and_written(tmp_path):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_catalog(
        sections_dir,
        [
            {
                "id": "fig-ingested1",
                "sha256": "1" * 64,
                "width_px": 100,
                "height_px": 100,
                "origin_relative_path": "assets/figures/ingested1.png",
                "caption": "Ingested figure",
                "source_role": "evidence",
                "origin_kind": "standalone",
            }
        ],
    )
    _write_specs(sections_dir, [{"label": "arch", "type": "chart", "source": "s1", "caption": "Arch"}])
    service = _service({"chart": FakeRenderer(type="chart", svg="<svg><rect/></svg>")}, FakeRasterizer())

    service.generate(sections_dir, assets_dir)

    catalog = _read_json(sections_dir / "figure-catalog.json")
    ids = {row["id"] for row in catalog["figures"]}
    assert "fig-ingested1" in ids
    assert len(catalog["figures"]) == 2
    generated_row = next(row for row in catalog["figures"] if row["id"] != "fig-ingested1")
    assert generated_row["origin_kind"] == "generated"
    # deterministic re-sort by id
    assert catalog["figures"] == sorted(catalog["figures"], key=lambda f: f["id"])


# --- 5.6 auto-bind label -> generated id, no-clobber, WARN on collision ---


def test_auto_binds_label_to_generated_id_no_clobber_warns_on_collision(tmp_path, capsys):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_bindings(sections_dir, {"arch-diagram": "fig-manual00"})
    _write_specs(
        sections_dir,
        [
            {"label": "arch-diagram", "type": "chart", "source": "s1"},  # collides with manual binding
            {"label": "new-diagram", "type": "chart", "source": "s2"},
        ],
    )
    service = _service(
        {"chart": FakeRenderer(type="chart", svg='<svg id="unique-per-call"><rect/></svg>')},
        FakeRasterizer(),
    )

    service.generate(sections_dir, assets_dir)

    bindings = _read_json(sections_dir / "figure-bindings.json")["bindings"]
    assert bindings["arch-diagram"] == "fig-manual00"  # manual binding preserved, never clobbered
    assert "new-diagram" in bindings
    assert bindings["new-diagram"] != "fig-manual00"
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "arch-diagram" in captured.err


# --- 5.7 renderer exception / missing toolchain -> warn+skip, continue ----


def test_renderer_exception_and_missing_toolchain_warn_skip_others_continue(tmp_path, capsys):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_specs(
        sections_dir,
        [
            {"label": "broken", "type": "mermaid", "source": "s1"},
            {"label": "ok", "type": "chart", "source": "s2"},
        ],
    )
    mermaid_renderer = FakeRenderer(
        type="mermaid", exc=RuntimeError("mmdc no encontrado en PATH; instale @mermaid-js/mermaid-cli")
    )
    chart_renderer = FakeRenderer(type="chart", svg="<svg><rect/></svg>")
    service = _service({"mermaid": mermaid_renderer, "chart": chart_renderer}, FakeRasterizer())

    result = service.generate(sections_dir, assets_dir)

    assert result.generated == 1
    assert result.skipped == 1
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "broken" in captured.err

    catalog = _read_json(sections_dir / "figure-catalog.json")
    assert len(catalog["figures"]) == 1


def test_rasterize_failure_warns_and_skips_others_continue(tmp_path, capsys):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_specs(
        sections_dir,
        [
            {"label": "broken", "type": "chart", "source": "s1"},
            {"label": "ok", "type": "chart", "source": "s2"},
        ],
    )
    calls = {"n": 0}

    class FlakyRasterizer(FakeRasterizer):
        def rasterize(self, svg_path: Path, png_path: Path) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("resvg no encontrado en PATH")
            super().rasterize(svg_path, png_path)

    chart_renderer = FakeRenderer(type="chart", svg="<svg><rect/></svg>")
    service = _service({"chart": chart_renderer}, FlakyRasterizer())

    result = service.generate(sections_dir, assets_dir)

    assert result.generated == 1
    assert result.skipped == 1
    captured = capsys.readouterr()
    assert "WARN" in captured.err


# --- null dims (un-dimensioned PNG) -> warn+skip ---------------------------


def test_null_dims_warns_and_skips(tmp_path, capsys):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_specs(sections_dir, [{"label": "arch", "type": "chart", "source": "s1"}])
    service = _service({"chart": FakeRenderer(type="chart", svg="<svg><rect/></svg>")}, FakeRasterizer(), dims=None)

    result = service.generate(sections_dir, assets_dir)

    assert result.generated == 0
    assert result.skipped == 1
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "arch" in captured.err
    assert not (sections_dir / "figure-catalog.json").exists()


# --- determinism: same specs+fakes twice -> byte-identical outputs --------


def test_write_failure_warns_and_skips_never_raises(tmp_path, capsys, monkeypatch):
    # A disk-write OSError (full/read-only assets_dir) on the .svg/.png must
    # WARN+skip THAT visual, never abort the whole run -- generate() never
    # raises (review WARNING: the atomic write was outside the per-visual
    # try/except).
    import docs.application.generate_visuals as gv

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(gv, "_atomic_write_bytes", _boom)
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_specs(sections_dir, [{"label": "a", "type": "chart", "source": "s", "caption": "A"}])
    service = _service({"chart": FakeRenderer(type="chart", svg='<svg id="x"><rect/></svg>')}, FakeRasterizer())

    result = service.generate(sections_dir, assets_dir)  # must not raise

    assert result.generated == 0
    assert result.skipped == 1
    assert "WARN" in capsys.readouterr().err


def test_determinism_same_specs_twice_is_byte_identical(tmp_path):
    def _run(root: Path) -> tuple[bytes, bytes, str]:
        sections_dir = root / "sections"
        assets_dir = root / "assets"
        _write_specs(
            sections_dir,
            [
                {"label": "alpha", "type": "chart", "source": "s1", "caption": "Alpha"},
                {"label": "beta", "type": "mermaid", "source": "s2", "caption": "Beta"},
            ],
        )
        service = _service(
            {
                "chart": FakeRenderer(type="chart", svg='<svg id="chart-1"><rect/></svg>'),
                "mermaid": FakeRenderer(type="mermaid", svg='<svg id="mermaid-1"><circle/></svg>'),
            },
            FakeRasterizer(),
        )
        service.generate(sections_dir, assets_dir)
        catalog_bytes = (sections_dir / "figure-catalog.json").read_bytes()
        bindings_bytes = (sections_dir / "figure-bindings.json").read_bytes()
        stems = sorted(p.stem for p in (assets_dir / "figures").glob("*.svg"))
        return catalog_bytes, bindings_bytes, ",".join(stems)

    run1 = _run(tmp_path / "run1")
    run2 = _run(tmp_path / "run2")
    assert run1 == run2
