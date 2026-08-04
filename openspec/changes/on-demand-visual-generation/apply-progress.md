# Apply Progress: On-Demand Visual Generation

Artifact store: hybrid (this file + Engram `sdd/on-demand-visual-generation/apply-progress`).

## Slice 1 — Domain foundation: ports, VisualSpec, normalize_svg, merge/merge_bindings — DONE

- [x] 1.1 RED `tests/unit/domain/test_visual_renderer_port.py` (new, 5 cases) +
  `tests/unit/domain/test_svg_rasterizer_port.py` (new, 2 cases).
  GREEN `src/docs/domain/ports/visual_renderer_port.py` (new: `VisualSpec`
  frozen dataclass, `VisualRendererPort` Protocol) +
  `src/docs/domain/ports/svg_rasterizer_port.py` (new: `SvgRasterizerPort`
  Protocol).
- [x] 1.2 RED `tests/unit/domain/test_svg_normalize.py` (new, 7 cases,
  including the critical byte-stability proof: two structurally-identical
  SVGs differing only in ids/comments/metadata dates -> identical sha256).
  GREEN `src/docs/domain/svg_normalize.py` (new): strips XML comments, strips
  `<metadata>`, collects `id="X"` in first-appearance order, rewrites every
  definition/reference form (`#X`, `url(#X)`, `href="X"`/`href="#X"`,
  `xlink:href="#X"`, `aria-labelledby="X"`) to `n0,n1,...`, replacing
  longest-id-first (proven via a CSS-selector `#abc`/`#a` collision test).
- [x] 1.3 RED extended `tests/unit/domain/test_figure_catalog.py` (+3 cases:
  no-clobber, resorted+deterministic, safe-to-rerun). GREEN
  `src/docs/domain/figure_catalog.py` — added `merge(existing_catalog: dict,
  generated: dict) -> dict`, union by `id`, existing wins on collision,
  re-sorted by `id` (same shape/determinism as `build()`).
- [x] 1.4 RED extended `tests/unit/domain/test_figure_binding.py` (+3 cases:
  adds-only-absent, never-clobbers, sorted+deterministic). GREEN
  `src/docs/domain/figure_binding.py` — added `merge_bindings(existing: dict,
  additions: dict) -> dict`, adds `label -> id` only when label absent,
  sorted-key output.
- [x] 1.5 Slice check green: 33 new/extended domain tests passed. Full suite:
  1396 passed, 0 failed, 7 skipped (zero regression). `ruff check` clean on
  all 9 changed/new files.

Commits (branch `feat/odvg-s1-domain`, off main `e43efec`):
- `9b4efba` feat(domain): add VisualRendererPort, VisualSpec, SvgRasterizerPort
- `117f657` feat(domain): add normalize_svg determinism pass for generated SVGs
- `7a8927e` feat(domain): add no-clobber merge() to figure_catalog
- `08b232a` feat(domain): add no-clobber merge_bindings() to figure_binding

Touched only Slice-1 (pure domain) files:
`src/docs/domain/ports/visual_renderer_port.py` (new),
`src/docs/domain/ports/svg_rasterizer_port.py` (new),
`src/docs/domain/svg_normalize.py` (new),
`src/docs/domain/figure_catalog.py` (modified, additive),
`src/docs/domain/figure_binding.py` (modified, additive),
`tests/unit/domain/test_visual_renderer_port.py` (new),
`tests/unit/domain/test_svg_rasterizer_port.py` (new),
`tests/unit/domain/test_svg_normalize.py` (new),
`tests/unit/domain/test_figure_catalog.py` (modified, extended),
`tests/unit/domain/test_figure_binding.py` (modified, extended).
No `application/`, `infrastructure/`, or `cli/` files touched (Slices 2-7
untouched — they depend on this slice's domain contracts).

## Slice 2 — `ChartSvgRenderer` (matplotlib Agg, declarative spec, no external toolchain) — DONE

- [x] 2.1 RED (THREAT MATRIX) `tests/unit/infrastructure/test_chart_svg_renderer.py`
  (new): `test_python_looking_source_text_renders_as_inert_data` — a series
  `label` that looks like Python code (`"__import__('os').system('id')"`)
  renders as literal chart text; `unittest.mock.patch` proves `builtins.eval`,
  `builtins.exec`, and `subprocess.run` are never invoked. Confirmed RED via
  `ModuleNotFoundError` (module did not exist) before implementation.
  GREEN `src/docs/infrastructure/visuals/chart_svg_renderer.py` (new):
  `ChartSvgRenderer` (`type = "chart"`), `render(spec)` parses `spec.source`
  with `json.loads` ONLY (never `eval`/`exec`), raising `ValueError` on
  malformed/non-JSON source.
- [x] 2.2 RED/GREEN same file: `test_render_bar_chart_produces_svg_text` — a
  well-formed `{"kind": "bar", "labels": [...], "series": [...]}` spec
  renders a string containing `<svg`. Bar/line/pie kind dispatch implemented
  inside `render()`.
- [x] 2.3 RED/GREEN same file:
  `test_render_plus_normalize_svg_is_byte_identical_across_two_runs` — render
  the same spec twice, normalize both via Slice 1's `normalize_svg`, assert
  `sha256` equal. Determinism knobs set inside `ChartSvgRenderer` (never in
  `normalize_svg`): `matplotlib.use("Agg")`, `rcParams["svg.hashsalt"]` fixed
  literal, `rcParams["svg.fonttype"]="none"`, pinned `font.family`,
  `savefig(..., metadata={"Date": None})`.
- [x] 2.4 RED/GREEN same file: `test_unknown_chart_kind_raises_documented_error`,
  `test_missing_required_field_raises_documented_error` — `ValueError` naming
  the invalid/missing field, caught by the future Slice-5 WARN+skip.

**Gotcha (undocumented in design, discovered during GREEN):** matplotlib's
backend + per-format canvas modules are lazily `importlib.import_module`'d on
first use, and that lazy path internally relies on `exec()`-based
pyplot-bridging machinery — colliding with the Threat-Matrix RED test's
`unittest.mock.patch("builtins.exec")`. Fixed by eagerly warming both the
figure-manager backend (`plt.switch_backend("Agg")`) and the SVG canvas
(`fig.savefig(io.BytesIO(), format="svg")` once) at module-import time, so
the lazy `exec()`-touching code path never runs inside a test's mock context.
Also: matplotlib's *automatic* legend collection silently drops any artist
`label` starting with `_` (its "private artist" convention) — an
agent-authored label starting with `__` would otherwise vanish from the
rendered chart. Fixed by building the legend explicitly via
`ax.legend(handles, names)` (bypasses that auto-collection filter) rather
than via each artist's `label=` kwarg.

- [x] Composition wiring RED/GREEN
  `tests/integration/test_deps_visual_renderers_wiring.py` (new):
  `test_deps_wires_a_chart_renderer_when_matplotlib_available` —
  `Deps().visual_renderers["chart"]` is a real `ChartSvgRenderer`. GREEN in
  `cli/_shared.py:Deps.__init__`: new `self.visual_renderers: dict[str, Any]`
  registry, `ChartSvgRenderer` construction guarded by `try/except Exception`
  (mirrors the existing `pypdfium2` guard immediately above it) so a
  matplotlib import failure leaves the renderer simply absent, never crashes
  `Deps()`.
- [x] `matplotlib` added as a hard dependency: `uv add matplotlib` (pyproject.toml
  `dependencies` + `uv.lock`).

Slice check green: 6 new tests (5 renderer + 1 wiring) passed. Full suite:
1403 passed, 0 failed, 7 skipped (zero regression vs. Slice 1's 1396 — net
+7 tests). `ruff check` clean on all changed files except one deliberate,
design-mandated deviation: `TRY004` on `chart_svg_renderer.py`'s
"source must be a JSON object" guard — tasks.md 2.1 explicitly specifies
`ValueError` (not `TypeError`) for every malformed-source case, uniformly,
so Slice 5's WARN+skip can catch one exception type.

Commits (branch `feat/odvg-s2-chart`, off main `6b19849`):
- build(deps): add matplotlib for chart SVG rendering
- feat(visuals): add ChartSvgRenderer (matplotlib Agg, declarative spec only)
- feat(cli): wire ChartSvgRenderer into Deps.visual_renderers registry
- docs(sdd): tick S2 tasks and record apply-progress for on-demand-visual-generation

Touched only Slice-2 files: `pyproject.toml` (modified), `uv.lock` (modified),
`src/docs/infrastructure/visuals/__init__.py` (new),
`src/docs/infrastructure/visuals/chart_svg_renderer.py` (new),
`src/docs/cli/_shared.py` (modified, additive `visual_renderers` block),
`tests/unit/infrastructure/test_chart_svg_renderer.py` (new),
`tests/integration/test_deps_visual_renderers_wiring.py` (new),
`openspec/changes/on-demand-visual-generation/tasks.md` (2.1-2.4 ticked),
`openspec/changes/on-demand-visual-generation/apply-progress.md` (this file).

Not started: Slices 3-7 (`MermaidSvgRenderer`, `SvgRasterizerPort` resvg
adapter, `GenerateVisualsService` + stage wiring, `html_render` sibling-SVG
swap + E2E, doctor checks + AGENTS.md). Slice 5.10's composition-wiring test
will extend `test_deps_visual_renderers_wiring.py` with a `"mermaid"`
assertion once Slice 3 lands.
