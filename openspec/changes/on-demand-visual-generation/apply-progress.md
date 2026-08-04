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

## Slice 3 — `MermaidSvgRenderer` (mmdc) + `resolve_mmdc` — DONE

- [x] 3.1 RED `tests/unit/infrastructure/test_tool_resolver_mmdc.py` (new,
  4 cases, mirrors `test_resolve_pandoc_executable.py`'s shape). Confirmed
  RED via `ModuleNotFoundError` before implementation. GREEN
  `src/docs/infrastructure/tools/mmdc_resolution.py` (new):
  `resolve_mmdc_executable(paths)` — PATH-then-`mmdc_bin`-then-
  `mmdc_fallbacks` resolution, same shape as `resolve_pandoc_executable`/
  `resolve_java_executable`. Wired `resolve_mmdc` onto
  `domain/ports/tool_resolver_port.py:ToolResolverPort` and
  `infrastructure/docx/tool_resolver_adapter.py:SystemToolResolverAdapter`.
- [x] 3.2 RED (THREAT MATRIX) `tests/unit/infrastructure/
  test_mermaid_svg_renderer.py::test_source_with_shell_metacharacters_never_reaches_a_shell`
  — mermaid source containing shell metacharacters (`` $(rm -rf /) `echo
  pwned` "; rm -rf / #" ``) is written to a temp `.mmd` file and asserted to
  never appear in any `subprocess.run` argv element; `subprocess.run` is
  asserted called with a list and `shell` never `True`. Confirmed RED via
  `ModuleNotFoundError` before implementation. GREEN
  `src/docs/infrastructure/visuals/mermaid_svg_renderer.py` (new):
  `MermaidSvgRenderer(tool_resolver, paths=None, scratch_root=None)`
  (`type = "mermaid"`); `render(spec)` resolves `mmdc` first, writes
  `spec.source` to `scratch_dir(self.scratch_root)/diagram.mmd` (reuses
  `infrastructure/ingest/atomic_ingest_write.py:scratch_dir` — same
  temp-file-not-shell-arg precedent as `pandoc_ingest_adapter.py`), invokes
  `subprocess.run([mmdc, "-i", str(tmp_mmd), "-o", str(tmp_svg),
  "--outputFormat", "svg"], check=True)` (fixed arg list, no `shell=True`),
  reads back `tmp_svg` text. `scratch_root` defaults to
  `tempfile.gettempdir()` (this port layer has no document-root context —
  `render(spec)` takes only the spec).
- [x] 3.3 RED/GREEN same file:
  `test_render_missing_mmdc_raises_runtime_error_with_guidance` — absent
  `mmdc` (`resolve_mmdc` → `None`) raises `RuntimeError` naming `mmdc` with
  install guidance (`npm install -g @mermaid-js/mermaid-cli`), covered by
  3.2's guard clause.
- [x] 3.4 RED/GREEN
  `tests/integration/test_mermaid_svg_renderer_integration.py::
  test_render_produces_svg_via_real_mmdc` — `@pytest.mark.skipif(shutil.which
  ("mmdc") is None, ...)` (mirrors the `pandoc`/`java`/`libreoffice` skipif
  precedent). `mmdc` absent in this dev environment → confirmed SKIPPED
  cleanly, not failed.
- [x] 3.5 RED/GREEN same integration file:
  `test_render_invalid_mermaid_syntax_raises_with_cause` — same skipif;
  `subprocess.run(..., check=True)`'s `CalledProcessError` propagates
  uncaught from `render()`. Also SKIPPED cleanly (mmdc absent).

Also added: `test_render_returns_svg_text_from_mmdc_output` and
`test_render_plus_normalize_svg_is_byte_identical_across_two_runs` (unit,
mocked mmdc writing a fixed/known SVG — proves `render` returns exactly what
`mmdc` wrote, and that render+`normalize_svg` is byte-stable across two
calls, same shape as Slice 2's chart determinism test).

- [x] Composition wiring RED/GREEN, extended
  `tests/integration/test_deps_visual_renderers_wiring.py`:
  `test_deps_wires_a_mermaid_renderer_regardless_of_mmdc_availability` —
  `Deps().visual_renderers["mermaid"]` is a real `MermaidSvgRenderer`
  regardless of `mmdc` PATH availability (resolution is deferred to
  `render()`, never checked at construction). GREEN in
  `cli/_shared.py:Deps.__init__`: `MermaidSvgRenderer(tool_resolver)`
  construction guarded by `try/except Exception` (mirrors the chart-renderer
  guard immediately above it) for defense-in-depth, though this renderer
  never touches `mmdc` at construction time — only `render()` does.

Slice check green: 11 new tests (4 tool-resolver + 4 mermaid-renderer unit +
1 wiring + 2 integration, both SKIPPED cleanly since `mmdc` is absent in this
dev environment) passed/skipped as expected. Full suite: 1412 passed, 0
failed, 9 skipped (vs. Slice 2's 1403 passed/7 skipped — net +9 passed, +2
skipped, zero regression). `ruff check` clean on all changed/new files.

Commits (branch `feat/odvg-s3-mermaid`, off main `8b7202f`):
- `feat(infrastructure): add resolve_mmdc tool resolution`
- `feat(visuals): add MermaidSvgRenderer (mmdc subprocess, scratch-file source)`
- `feat(cli): wire MermaidSvgRenderer into Deps.visual_renderers registry`
- `docs(sdd): tick S3 tasks and record apply-progress for on-demand-visual-generation`

Touched only Slice-3 files: `src/docs/infrastructure/tools/mmdc_resolution.py`
(new), `src/docs/domain/ports/tool_resolver_port.py` (modified, additive),
`src/docs/infrastructure/docx/tool_resolver_adapter.py` (modified,
additive), `src/docs/infrastructure/visuals/mermaid_svg_renderer.py` (new),
`src/docs/cli/_shared.py` (modified, additive `mermaid` registry block),
`tests/unit/infrastructure/test_tool_resolver_mmdc.py` (new),
`tests/unit/infrastructure/test_mermaid_svg_renderer.py` (new),
`tests/integration/test_mermaid_svg_renderer_integration.py` (new),
`tests/integration/test_deps_visual_renderers_wiring.py` (modified,
extended), `openspec/changes/on-demand-visual-generation/tasks.md`
(3.1-3.5 ticked), `openspec/changes/on-demand-visual-generation/
apply-progress.md` (this file).

## Slice 4 — `SvgRasterizerPort` resvg adapter + `resolve_resvg` + PNG dims — DONE

- [x] 4.1 RED `tests/unit/infrastructure/test_tool_resolver_resvg.py` (new,
  4 cases, exact mirror of `test_tool_resolver_mmdc.py`'s shape). Confirmed
  RED via `ModuleNotFoundError` before implementation. GREEN
  `src/docs/infrastructure/tools/resvg_resolution.py` (new):
  `resolve_resvg_executable(paths)` — PATH-then-`resvg_bin`-then-
  `resvg_fallbacks` resolution, same shape as `resolve_mmdc_executable`.
  Wired `resolve_resvg` onto `domain/ports/tool_resolver_port.py:
  ToolResolverPort` and `infrastructure/docx/tool_resolver_adapter.py:
  SystemToolResolverAdapter`.
- [x] 4.2 RED (THREAT MATRIX) `tests/unit/infrastructure/
  test_resvg_rasterizer_adapter.py::test_rasterize_never_uses_shell` — patches
  `subprocess.run`, asserts a fixed arg list (`[resvg, str(svg_path),
  str(png_path), "--use-fonts-dir", str(font_dir)]`), a list (never a
  string), `shell` never `True`, paths passed as explicit args. Confirmed RED
  via `ModuleNotFoundError` before implementation. GREEN
  `src/docs/infrastructure/visuals/resvg_rasterizer_adapter.py` (new):
  `ResvgRasterizerAdapter(tool_resolver, paths=None, font_dir=None)`
  implementing `SvgRasterizerPort.rasterize(svg_path, png_path) -> None`;
  invokes `subprocess.run([resvg, str(svg_path), str(png_path)] + optional
  ["--use-fonts-dir", str(font_dir)], check=True)` (fixed list, no
  `shell=True`). `font_dir` defaults to `None` (no font is vendored by this
  repo yet — design.md Open Questions — so the flag is simply omitted when
  absent rather than inventing a vendored-font asset); also covered by
  `test_rasterize_without_font_dir_omits_fonts_dir_flag`.
- [x] 4.3 RED/GREEN same file:
  `test_missing_resvg_raises_runtime_error_with_guidance` — absent `resvg`
  (`resolve_resvg` → `None`) raises `RuntimeError` naming `resvg` with
  install guidance, covered by 4.2's guard clause (mirrors 3.3's shape).
- [x] 4.4 RED/GREEN
  `tests/integration/test_resvg_rasterizer_adapter_integration.py::
  test_rasterize_svg_to_png_with_dims` — `@pytest.mark.skipif(shutil.which
  ("resvg") is None, ...)` (mirrors the `mmdc`/`pandoc`/`java`/`libreoffice`
  skipif precedent); rasterizes a real SVG fixture, then asserts the
  EXISTING `PythonDocxImageMetadataAdapter.read_dimensions(png_path)` (no
  new dims port) returns non-null `width_px`/`height_px`. `resvg` absent in
  this dev environment → confirmed SKIPPED cleanly, not failed. Also added
  `test_rasterize_same_svg_twice_is_byte_identical` (same skipif) — the
  determinism proof from design.md's Testing section ("resvg SVG→PNG+dims"),
  also skipped cleanly here.

- [x] Composition wiring RED/GREEN, extended
  `tests/integration/test_deps_visual_renderers_wiring.py`:
  `test_deps_wires_a_resvg_rasterizer_regardless_of_resvg_availability` —
  `Deps().svg_rasterizer` is a real `ResvgRasterizerAdapter` regardless of
  `resvg` PATH availability (resolution is deferred to `rasterize()`, never
  checked at construction). GREEN in `cli/_shared.py:Deps.__init__`:
  `self.svg_rasterizer = ResvgRasterizerAdapter(tool_resolver)` construction
  guarded by `try/except Exception` (mirrors the mermaid-renderer guard
  immediately above it), falling back to `self.svg_rasterizer = None` on
  import failure — never crashes `Deps()`.

Slice check green: 11 new tests (4 tool-resolver + 3 rasterizer-adapter unit
+ 1 wiring + 2 integration [both SKIPPED cleanly, `resvg` absent in this dev
environment], + the wiring test itself) passed/skipped as expected. Full
suite: 1420 passed, 0 failed, 11 skipped (vs. Slice 3's 1412 passed/9
skipped — net +8 passed, +2 skipped, zero regression). `ruff check` clean on
all changed/new files.

Commits (branch `feat/odvg-s4-resvg`, off main `83ed4a2`):
- `feat(infrastructure): add resolve_resvg tool resolution`
- `feat(visuals): add ResvgRasterizerAdapter (resvg subprocess, no shell)`
- `feat(cli): wire ResvgRasterizerAdapter into Deps.svg_rasterizer`
- `docs(sdd): tick S4 tasks and record apply-progress for on-demand-visual-generation`

Touched only Slice-4 files: `src/docs/infrastructure/tools/
resvg_resolution.py` (new), `src/docs/domain/ports/tool_resolver_port.py`
(modified, additive), `src/docs/infrastructure/docx/tool_resolver_adapter.py`
(modified, additive), `src/docs/infrastructure/visuals/
resvg_rasterizer_adapter.py` (new), `src/docs/cli/_shared.py` (modified,
additive `svg_rasterizer` block), `tests/unit/infrastructure/
test_tool_resolver_resvg.py` (new), `tests/unit/infrastructure/
test_resvg_rasterizer_adapter.py` (new), `tests/integration/
test_resvg_rasterizer_adapter_integration.py` (new), `tests/integration/
test_deps_visual_renderers_wiring.py` (modified, extended),
`openspec/changes/on-demand-visual-generation/tasks.md` (4.1-4.4 ticked),
`openspec/changes/on-demand-visual-generation/apply-progress.md` (this
file).

Not started: Slices 5-7 (`GenerateVisualsService` + stage wiring, `html_render`
sibling-SVG swap + E2E, doctor checks + AGENTS.md).
