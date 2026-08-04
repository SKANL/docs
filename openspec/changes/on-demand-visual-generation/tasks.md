# Tasks: On-Demand Visual Generation

Strict TDD throughout: every task's test sub-step MUST be written and run RED
before the implementation sub-step is written. `uv run pytest <path>` is the
gate for each checkbox.

`delivery_strategy: ask-on-risk` — the orchestrator MUST confirm the
chaining/PR-boundary decision in the Review Workload Forecast (bottom of this
file) before `sdd-apply` starts, since Slice 5's forecast exceeds the
400-line budget on its own.

Backward-compat invariant (holds across every slice): absent
`sections/visual-specs.json` MUST leave the pipeline byte-identical to today
— run the existing acceptance/characterization suite
(`tests/integration/test_technical_report_srs_acceptance.py`,
`tests/integration/test_documento_generico_acceptance.py`) unmodified after
each slice and treat any diff as a regression.

---

## Slice 1 — Domain foundation: ports, VisualSpec, normalize_svg, merge/merge_bindings

Grounded in: `domain/figure_catalog.py:18` (`build`, sort-by-id pattern),
`domain/figure_binding.py:10` (`BoundFigure` frozen dataclass style),
`deterministic_zip.py:60` (normalization-as-last-step precedent).
Spec: document-visuals "Extensible Visual-Renderer Registry"; asset-management
"Deterministic Figure-Catalog Merge" (ADDED).

- [x] 1.1 **Test first** — `tests/unit/domain/test_visual_renderer_port.py`:
      `VisualSpec` is a frozen dataclass with `label: str`, `type: str`,
      `source: str`, `caption: str = ""`; instantiation succeeds and mutation
      raises `FrozenInstanceError`. `VisualRendererPort` is a `Protocol` with
      a `type: str` attribute and `render(self, spec: VisualSpec) -> str`.
      **Implement** — create `src/docs/domain/ports/visual_renderer_port.py`
      (`VisualSpec`, `VisualRendererPort`) and
      `src/docs/domain/ports/svg_rasterizer_port.py`
      (`SvgRasterizerPort.rasterize(svg_path: Path, png_path: Path) -> None`).
      Run: `uv run pytest tests/unit/domain/test_visual_renderer_port.py`.

- [x] 1.2 **Test first** — `tests/unit/domain/test_svg_normalize.py`:
      `normalize_svg(text)` (a) strips `<!-- ... -->` XML comments,
      (b) strips `<metadata>...</metadata>` blocks, (c) collects every
      `id="X"` in first-appearance order and rewrites it and every
      reference (`#X`, `url(#X)`, `href="X"`/`href="#X"`,
      `xlink:href="#X"`, `aria-labelledby="X"`) to `n0`, `n1`, … in that same
      order, replacing longest-id-first so no substring collision (e.g. an id
      `"a"` must not corrupt a reference to `"abc"`). Assert byte-identical
      output across two calls on the same input.
      **Implement** — create `src/docs/domain/svg_normalize.py:normalize_svg`
      (pure, regex-based per design's `# ponytail:` note — no XML parser).
      Run: `uv run pytest tests/unit/domain/test_svg_normalize.py`.

- [x] 1.3 **Test first** — `tests/unit/domain/test_figure_catalog.py` (extend
      existing file): `test_merge_preserves_all_entries_no_clobber`
      (existing wins on `id` collision, generated never overwrites ingest),
      `test_merge_is_resorted_and_deterministic` (same two inputs, either
      order → byte-identical, sorted by `id`), `test_merge_safe_to_rerun`
      (re-merging an already-merged entry set produces no duplicate).
      **Implement** — add pure `merge(existing: dict, generated: dict) -> dict`
      to `src/docs/domain/figure_catalog.py` (union by `id`, existing wins,
      re-sort by `id` — same shape as `build()`'s output). I/O stays out of
      this function.
      Run: `uv run pytest tests/unit/domain/test_figure_catalog.py`.

- [x] 1.4 **Test first** — `tests/unit/domain/test_figure_binding.py` (extend
      existing file): `test_merge_bindings_adds_only_absent_labels`,
      `test_merge_bindings_never_clobbers_existing_label` (existing binding
      for a label wins even if `additions` re-declares it),
      `test_merge_bindings_output_is_sorted_and_deterministic`.
      **Implement** — add pure
      `merge_bindings(existing: dict, additions: dict) -> dict` to
      `src/docs/domain/figure_binding.py`.
      Run: `uv run pytest tests/unit/domain/test_figure_binding.py`.

## Slice 2 — `ChartSvgRenderer` (matplotlib Agg, declarative spec, no external toolchain)

Grounded in: design.md Decision "chart spec is DECLARATIVE data, never
executed code"; Threat Matrix row "Documentation-like / execution boundary".
Spec: document-visuals "Chart entry produces sibling SVG and PNG without a
Node/Chrome toolchain".

- [x] 2.1 **Test first (THREAT MATRIX RED)** —
      `tests/unit/infrastructure/test_chart_svg_renderer.py::
      test_python_looking_source_text_renders_as_inert_data`: a spec whose
      `source` JSON contains a string value that looks like Python code
      (e.g. `"__import__('os').system('id')"` as a series label) renders
      successfully as literal text with zero side effects (no subprocess, no
      file/env mutation) — assert via `unittest.mock.patch` that `eval`,
      `exec`, and `subprocess` are never invoked by this renderer, and the
      output SVG contains the label as escaped text.
      **Implement** — create
      `src/docs/infrastructure/visuals/chart_svg_renderer.py`:
      `ChartSvgRenderer` (`type = "chart"`), `render(spec)` parses
      `spec.source` with `json.loads` ONLY (never `eval`/`exec`), raising a
      documented exception (`ValueError`) on malformed/non-JSON source so the
      Slice-5 service can WARN+skip it.
      Run: `uv run pytest tests/unit/infrastructure/test_chart_svg_renderer.py`.

- [x] 2.2 **Test first** — same file:
      `test_render_bar_chart_produces_svg_text` — a well-formed declarative
      spec (`{"kind": "bar", "labels": [...], "series": [...]}`) renders a
      string containing `<svg`.
      **Implement** — chart-kind dispatch inside `render()`
      (`matplotlib.use("Agg")` set once at import time; `savefig(format="svg")`
      to an in-memory buffer, returning `.getvalue().decode()`).
      Run: `uv run pytest tests/unit/infrastructure/test_chart_svg_renderer.py`.

- [x] 2.3 **Test first** —
      `test_render_plus_normalize_svg_is_byte_identical_across_two_runs`
      (exercises Slice 1's `normalize_svg` on this renderer's raw output):
      render the same spec twice, normalize both, assert `sha256` equal.
      **Implement** — determinism knobs: `rcParams["svg.hashsalt"] = <fixed
      literal>`, `rcParams["svg.fonttype"] = "none"`, pinned `font.family`,
      `savefig(..., metadata={"Date": None})` — set inside `ChartSvgRenderer`,
      never in `normalize_svg` (design.md: "Renderer-side determinism knobs").
      Run: `uv run pytest tests/unit/infrastructure/test_chart_svg_renderer.py`.

- [x] 2.4 **Test first** — `test_unknown_chart_kind_raises_documented_error`,
      `test_missing_required_field_raises_documented_error` (e.g. no
      `labels`).
      **Implement** — input validation raising `ValueError` with a message
      naming the missing/invalid field (caught by Slice 5's WARN+skip).
      Run: `uv run pytest tests/unit/infrastructure/test_chart_svg_renderer.py`.

## Slice 3 — `MermaidSvgRenderer` (mmdc) + `resolve_mmdc`

Grounded in: `pandoc_ingest_adapter.py:38` (`RuntimeError` when tool absent —
mirrored here), `atomic_ingest_write.py:13` (`scratch_dir` — mermaid source
written to a temp file, not a shell arg). Threat Matrix row "Subprocess arg
composition".

- [x] 3.1 **Test first** — `tests/unit/infrastructure/test_tool_resolver_mmdc.py`:
      `SystemToolResolverAdapter.resolve_mmdc(paths)` resolves `mmdc` from
      PATH (mirrors `resolve_pandoc_executable`'s shape/fallback contract).
      **Implement** — add `resolve_mmdc(self, paths: dict[str, Any]) -> str |
      None` to `domain/ports/tool_resolver_port.py:ToolResolverPort` and to
      `infrastructure/docx/tool_resolver_adapter.py:SystemToolResolverAdapter`
      (new small resolver function alongside `resolve_pandoc_executable`,
      e.g. in a new `infrastructure/tools/mmdc_resolution.py` mirroring
      `java_resolution.py`'s separation).
      Run: `uv run pytest tests/unit/infrastructure/test_tool_resolver_mmdc.py`.

- [x] 3.2 **Test first (THREAT MATRIX RED)** —
      `tests/unit/infrastructure/test_mermaid_svg_renderer.py::
      test_source_with_shell_metacharacters_never_reaches_a_shell`: a spec
      `source` containing shell metacharacters (e.g. `"; rm -rf / #"`) as
      mermaid diagram text; patch `subprocess.run` and assert (a) it is
      called with a list (never a string) and `shell` is never `True`, (b)
      the mermaid text is written to a temp file (via `scratch_dir`) and
      passed to `mmdc` as a file path argument, never interpolated into a
      shell string.
      **Implement** — create
      `src/docs/infrastructure/visuals/mermaid_svg_renderer.py`:
      `MermaidSvgRenderer(tool_resolver)` (`type = "mermaid"`), `render(spec)`
      resolves `mmdc` first (raise `RuntimeError` with install guidance if
      absent — Slice 5 catches this for WARN+skip), writes `spec.source` to a
      temp `.mmd` file under `scratch_dir`, invokes
      `subprocess.run([mmdc, "-i", str(tmp_mmd), "-o", str(tmp_svg),
      "--outputFormat", "svg"], check=True)` (fixed arg list, no `shell=True`).
      Run: `uv run pytest tests/unit/infrastructure/test_mermaid_svg_renderer.py`.

- [x] 3.3 **Test first** — same file:
      `test_render_missing_mmdc_raises_runtime_error_with_guidance`.
      **Implement** — covered by 3.2's guard clause; assert the exact
      message names `mmdc` and install guidance.
      Run: `uv run pytest tests/unit/infrastructure/test_mermaid_svg_renderer.py`.

- [x] 3.4 **Test first** —
      `tests/integration/test_mermaid_svg_renderer_integration.py::
      test_render_produces_svg_via_real_mmdc` — `@pytest.mark.skipif` when
      `mmdc` is absent from PATH; a well-formed mermaid `source` renders SVG
      text containing `<svg`.
      **Implement** — none beyond 3.2 (this is a real-toolchain integration
      check of the same code path).
      Run: `uv run pytest tests/integration/test_mermaid_svg_renderer_integration.py`.

- [x] 3.5 **Test first** — same integration file:
      `test_render_invalid_mermaid_syntax_raises_with_cause` — malformed
      mermaid source causes `mmdc` to exit non-zero; renderer re-raises with
      the subprocess failure detail (Slice 5 catches, WARNs, skips).
      **Implement** — let `subprocess.run(..., check=True)`'s
      `CalledProcessError` propagate uncaught from `render()` (caller layer
      owns the catch, per design's stage-callable WARN+skip pattern).
      Run: `uv run pytest tests/integration/test_mermaid_svg_renderer_integration.py`.

## Slice 4 — `SvgRasterizerPort` resvg adapter + `resolve_resvg` + PNG dims

Grounded in: `ingest.py:1049` (`ImageMetadataPort.read_dimensions` reused
exactly — no new dims port). Threat Matrix row "Subprocess arg composition".

- [x] 4.1 **Test first** —
      `tests/unit/infrastructure/test_tool_resolver_resvg.py`: same shape as
      3.1 for `resolve_resvg`.
      **Implement** — add `resolve_resvg` to `ToolResolverPort` and
      `SystemToolResolverAdapter` (mirrors 3.1's pattern, e.g.
      `infrastructure/tools/resvg_resolution.py`).
      Run: `uv run pytest tests/unit/infrastructure/test_tool_resolver_resvg.py`.

- [x] 4.2 **Test first (THREAT MATRIX RED)** —
      `tests/unit/infrastructure/test_resvg_rasterizer_adapter.py::
      test_rasterize_never_uses_shell`: patch `subprocess.run`, assert a
      fixed arg list (`[resvg, str(svg_path), str(png_path), "--use-fonts-dir",
      <pinned-font-dir>]`), `shell` never `True`, paths passed as explicit
      args (never string-interpolated).
      **Implement** — create
      `src/docs/infrastructure/visuals/resvg_rasterizer_adapter.py`:
      `ResvgRasterizerAdapter(tool_resolver, font_dir=...)` implementing
      `SvgRasterizerPort.rasterize`.
      Run: `uv run pytest tests/unit/infrastructure/test_resvg_rasterizer_adapter.py`.

- [x] 4.3 **Test first** — same file:
      `test_missing_resvg_raises_runtime_error_with_guidance` (mirrors 3.3).
      **Implement** — guard clause raising `RuntimeError` when
      `resolve_resvg` returns `None`.
      Run: `uv run pytest tests/unit/infrastructure/test_resvg_rasterizer_adapter.py`.

- [x] 4.4 **Test first** —
      `tests/integration/test_resvg_rasterizer_adapter_integration.py::
      test_rasterize_svg_to_png_with_dims` — `@pytest.mark.skipif` when
      `resvg` is absent; rasterize a real SVG fixture, then assert
      `PythonDocxImageMetadataAdapter.read_dimensions(png_path)` (the
      EXISTING port, reused unchanged) returns non-null `width_px`/`height_px`.
      **Implement** — none beyond 4.2/4.3; this is a real-toolchain
      integration check confirming the reused dims port works against
      resvg's PNG output.
      Run: `uv run pytest tests/integration/test_resvg_rasterizer_adapter_integration.py`.

## Slice 5 — `GenerateVisualsService` + stage wiring + ordering + auto-bind + catalog merge

**Largest slice — forecast exceeds the 400-line PR budget on its own (see
Review Workload Forecast). `delivery_strategy: ask-on-risk` — confirm with
the orchestrator whether to further split 5.1–5.7 (service, PR 5a) from
5.8–5.10 (stage/composition-root wiring, PR 5b) before `sdd-apply` begins.**

**Resolved: split into 5a/5b (option 2).** 5.1–5.7 (`GenerateVisualsService`
alone) landed on branch `feat/odvg-s5a-service`; 5.8–5.10 (pipeline stage +
composition-root wiring) are a separate PR (5b), not started here.

Grounded in: `ingest.py` per-item try/except WARN+skip pattern,
`application/pipeline.py:306` (`stage_ingest`'s errors-list-not-crash shape),
`figure_resolver.py:15` (`_read_json_fail_open` — same fail-open read for
`visual-specs.json`), `domain/pipeline.py:33` (`pipeline_stage_plan`).

- [x] 5.1 **Test first** —
      `tests/unit/application/test_generate_visuals_service.py::
      test_registry_dispatch_by_type` — two fake `VisualRendererPort`s
      registered by `type`; `GenerateVisualsService.generate(...)` routes
      each spec to its registered renderer.
      `test_unregistered_type_warns_and_skips` — an entry with an
      unregistered `type` is WARNed (capture stderr) naming the type, and
      does not crash; other entries still process.
      **Implement** — create `src/docs/application/generate_visuals.py`:
      `GenerateVisualsService(renderers: dict[str, VisualRendererPort],
      rasterizer: SvgRasterizerPort, image_metadata: ImageMetadataPort,
      writer)`.
      Run: `uv run pytest tests/unit/application/test_generate_visuals_service.py`.

- [x] 5.2 **Test first** — same file:
      `test_missing_visual_specs_file_is_noop` — no
      `sections/visual-specs.json` → service returns a no-op result; catalog
      and bindings files are untouched (not even re-written).
      **Implement** — fail-open read of `visual-specs.json` (same shape as
      `figure_resolver._read_json_fail_open`): absent/malformed file → `[]`.
      Run: `uv run pytest tests/unit/application/test_generate_visuals_service.py`.

- [x] 5.3 **Test first** — same file:
      `test_malformed_entry_warns_naming_missing_field_others_still_process`
      — one entry missing `source`, one well-formed entry in the same list;
      the malformed one is WARNed naming the field, the well-formed one is
      still rendered/cataloged/bound.
      **Implement** — per-entry shape validation before dispatch (required:
      `label`, `type`, `source`).
      Run: `uv run pytest tests/unit/application/test_generate_visuals_service.py`.

- [x] 5.4 **Test first** — same file:
      `test_well_formed_entry_writes_sibling_svg_and_png_with_shared_stem`
      — asserts `stem = f"visual-{sha8_of_normalized_svg}"`,
      `assets_dir/figures/<stem>.svg` and `<stem>.png` both exist,
      `FigureEntry(origin_kind="generated", sha256=sha256(png_bytes), ...)`
      is produced with dims from `image_metadata.read_dimensions(png_path)`.
      **Implement** — per-entry pipeline: `renderer.render(spec)` → raw SVG
      → Slice 1's `normalize_svg` (domain, pure) → compute stem from its
      sha8 → write `.svg` → `rasterizer.rasterize(svg_path, png_path)` →
      read PNG bytes + dims → build `FigureEntry`.
      Run: `uv run pytest tests/unit/application/test_generate_visuals_service.py`.

- [x] 5.5 **Test first** — same file:
      `test_generated_entries_merged_into_existing_catalog_and_written` —
      given a fixture `figure-catalog.json` from ingest, service output
      merges via Slice 1's `merge()` and writes the result (via the
      existing writer port, e.g. `FilesystemIngestArtifactWriter.write_json`
      reused — no new writer port).
      **Implement** — call `figure_catalog.merge(existing, generated)`,
      write via injected writer.
      Run: `uv run pytest tests/unit/application/test_generate_visuals_service.py`.

- [x] 5.6 **Test first** — same file:
      `test_auto_binds_label_to_generated_id_no_clobber_warns_on_collision`
      — a generated entry with `label: "arch-diagram"` writes
      `"arch-diagram" -> "fig-<sha8>"` into `figure-bindings.json` via
      Slice 1's `merge_bindings()`; when a manual binding for the same label
      already exists, it is left unchanged and the stage WARNs naming the
      label collision.
      **Implement** — call `figure_binding.merge_bindings(existing,
      {label: catalog_id})` per successfully generated entry, write via the
      same writer.
      Run: `uv run pytest tests/unit/application/test_generate_visuals_service.py`.

- [x] 5.7 **Test first** — same file:
      `test_renderer_exception_and_missing_toolchain_warn_skip_others_continue`
      — a `RuntimeError` from `render()` (missing toolchain, per Slices 3/4)
      or `rasterize()` is caught per-entry, WARNed naming the cause, and does
      not stop other entries from processing.
      **Implement** — wrap the per-entry pipeline (5.4) in
      `try/except Exception` at the entry-loop level (mirrors
      `ingest.py`'s per-item catch), never a bare `except: pass`.
      Run: `uv run pytest tests/unit/application/test_generate_visuals_service.py`.

- [x] 5.8 **Test first** —
      `tests/unit/domain/test_pipeline.py::
      test_generate_visuals_runs_after_ingest_before_assemble_in_all` and
      `test_generate_visuals_prepended_before_assemble_stages_in_assemble` —
      `pipeline_stage_plan("all", assemble)` has `"generate-visuals"`
      strictly after `"build-context-index"` (last ingest-set stage) and
      strictly before the first `assemble`-supplied stage;
      `pipeline_stage_plan("assemble", assemble)` also prepends
      `"generate-visuals"` before the renderer's own stages (design.md:
      "prepended to the assemble stages for both `assemble` and `all`").
      **Implement** — add `_GENERATE_VISUALS: list[tuple[str, bool]] =
      [("generate-visuals", False)]` to `domain/pipeline.py`; prepend it to
      `assemble` in both the `stage_set == "assemble"` and `"all"` branches
      of `pipeline_stage_plan`.
      Run: `uv run pytest tests/unit/domain/test_pipeline.py`.

- [x] 5.9 **Test first** —
      `tests/integration/test_pipeline_service.py` (extend or add adjacent
      file): `test_stage_generate_visuals_is_wired_and_never_fail_fast` —
      `PipelineService._stage_callables(...)["generate-visuals"]` invokes
      `GenerateVisualsService.generate(...)` with the resolved
      `sections_dir`/`assets_dir` paths, returns `ok=True` even when a WARN
      detail is present (fail_fast=False per 5.8's stage tuple — a failing
      visual never blocks `assemble`).
      **Implement** — add `generate_visuals_service: GenerateVisualsService`
      to `PipelineService.__init__`; add `stage_generate_visuals()` to
      `_stage_callables` reading `sections_dir`/`assets_dir` from `config`,
      returning `(True, detail)` always (per-visual failures are WARN
      details, not stage failures — matches `stage_collect_issues`'s
      best-effort shape).
      Run: `uv run pytest tests/integration/test_pipeline_service.py`.

- [x] 5.10 **Test first** —
      `tests/integration/test_deps_visual_renderers_wiring.py`:
      `Deps().pipeline` has a `generate_visuals_service` wired with a
      `visual_renderers` registry containing `"chart"` and `"mermaid"` keyed
      renderers, a resvg-backed `SvgRasterizerPort`, reusing the existing
      `PythonDocxImageMetadataAdapter` for dims (no new dims port
      instantiated).
      **Implement** — in `cli/_shared.py:Deps.__init__`: construct
      `ChartSvgRenderer()`, `MermaidSvgRenderer(tool_resolver)`,
      `ResvgRasterizerAdapter(tool_resolver)`, assemble
      `visual_renderers = {"chart": ..., "mermaid": ...}`, construct
      `GenerateVisualsService(visual_renderers, rasterizer,
      image_metadata=PythonDocxImageMetadataAdapter(),
      writer=FilesystemIngestArtifactWriter())`, pass it into
      `PipelineService(...)`.
      Run: `uv run pytest tests/integration/test_deps_visual_renderers_wiring.py`.

## Slice 6 — `html_render` sibling `.png→.svg` swap + E2E byte-identity

Grounded in: `application/html_render.py:66-72` (`build_bound_figures_resolver`
call site — swap happens right after it, before `strip_frontmatter_to_temp`).
Spec: document-render "HTML Prefers Sibling SVG for a Bound Figure".

- [ ] 6.1 **Test first** —
      `tests/unit/application/test_html_render_svg_swap.py`:
      `test_bound_figure_with_sibling_svg_swaps_to_svg_path` — a
      `BoundFigure` whose `.path` ends in `.png` and has a same-stem, same-dir
      `.svg` file on disk is rewritten to point at the `.svg` before
      `strip_frontmatter_to_temp` runs; dims/caption/label are unchanged.
      `test_bound_figure_without_sibling_svg_is_unaffected` — no swap when no
      sibling `.svg` exists (regression guard for plain ingested photos).
      **Implement** — in `application/html_render.py:build`, after
      `build_bound_figures_resolver(...)`, map each `BoundFigure` to a
      dataclass-replaced copy whose `.path` is the sibling `.svg` when
      `Path(path).with_suffix(".svg").exists()`.
      Run: `uv run pytest tests/unit/application/test_html_render_svg_swap.py`.

- [ ] 6.2 **Test first (characterization)** —
      `tests/unit/application/test_docx_assembly_ignores_sibling_svg.py`:
      `test_docx_always_embeds_png_even_with_sibling_svg` — the SAME bound
      figure (PNG + sibling SVG both present) still embeds the PNG when
      built to docx (pandoc#9195 blocker — locks the "docx never sees the
      swap" contract from regressing).
      **Implement** — none (this proves `docx_assembly.py` is untouched by
      Slice 6; if it fails, Slice 6 leaked into the docx path).
      Run: `uv run pytest tests/unit/application/test_docx_assembly_ignores_sibling_svg.py`.

- [ ] 6.3 **Test first (E2E)** —
      `tests/integration/test_generate_visuals_e2e.py`:
      `test_chart_only_pipeline_e2e_docx_png_html_svg` (no `@skipif` — chart
      needs only matplotlib) — full pipeline `ingest` → `generate-visuals` →
      `assemble` (docx + html) for a doc with one `chart`-type
      `visual-specs.json` entry; assert docx embeds the PNG and HTML embeds
      the SVG.
      `test_mermaid_and_chart_pipeline_e2e_byte_identical` (`@pytest.mark.
      skipif` when `mmdc`/`resvg` absent) — one mermaid + one chart entry;
      run the full pipeline twice independently; assert
      `figure-catalog.json`, `figure-bindings.json`, generated `.svg`/`.png`,
      and final docx/html output are all byte-identical (`sha256`) across
      both runs.
      **Implement** — none beyond Slices 1–6 wiring; this is the integration
      proof of the whole feature.
      Run: `uv run pytest tests/integration/test_generate_visuals_e2e.py`.

- [ ] 6.4 **Regression gate (no new test)** — run the full existing suite
      unmodified and confirm zero regressions, in particular
      `tests/integration/test_technical_report_srs_acceptance.py` and
      `tests/integration/test_documento_generico_acceptance.py` (no
      `visual-specs.json` present in either fixture doc → backward-compat
      no-op holds).
      Run: `uv run pytest`.

## Slice 7 — doctor capability checks + `pyproject.toml` + AGENTS.md authoring docs

Grounded in: `doctor.py:203` (`_capability_checks`, `Check(required=False)`
pattern for `pdf_page_render`/`pdf_raster_extract`), `tests/unit/
test_agents_md_content.py` (existing AGENTS.md content-assertion convention).

- [ ] 7.1 **Test first** —
      `tests/integration/test_doctor_service.py` (extend existing file):
      `test_resvg_and_mmdc_capability_checks_required_false` — `run_doctor()`
      includes `Check("resvg", ..., required=False)` and
      `Check("mmdc", ..., required=False)`, each with install guidance in its
      detail when absent (mirrors `pdf_page_render`/`pdf_raster_extract`
      shape exactly).
      **Implement** — in `application/doctor.py`, add resvg/mmdc checks
      (via `self.tool_resolver.resolve_resvg`/`resolve_mmdc` from Slices
      3/4) either in `_capability_checks` or alongside the `pandoc`/
      `libreoffice` checks in `run_doctor` (same optional-toolchain
      `required=False` shape as `libreoffice`).
      Run: `uv run pytest tests/integration/test_doctor_service.py`.

- [ ] 7.2 **Mechanical (no test — trivial dependency declaration)** — add
      `matplotlib` to `pyproject.toml`'s `dependencies` (hard new pip dep,
      per design's Migration/Rollout: "matplotlib is the only hard new pip
      dep"). Add a comment documenting `resvg` and `mmdc` as optional,
      PATH-resolved external toolchain (not a pip/npm dependency of this
      project) next to the dependency block or in a README/AGENTS.md
      toolchain section.
      Run: `uv sync` (or `uv run pytest` to confirm nothing broke by the dep
      addition).

- [ ] 7.3 **Test first** — `tests/unit/test_agents_md_content.py` (extend
      existing file, same convention as `test_documents_format_selection_
      and_pdf_non_determinism_caveat`):
      `test_documents_visual_specs_authoring_format` — asserts `AGENTS.md`
      contains `visual-specs.json`, the entry shape `label`/`type`/`source`/
      `caption`, both valid `type` values `"mermaid"` and `"chart"`, and a
      statement of the auto-bind / WARN+skip / no-op-when-absent contract.
      **Implement** — add a `visual-specs.json` authoring section to
      `AGENTS.md` (repo root — the single-source file per `_read_agents_
      guide`'s ADR-B, no separate wheel-packaged copy to author) describing:
      the file's location (`sections/visual-specs.json`), entry shape, the
      two built-in `type`s and their `source` shape (chart: declarative JSON
      `{"kind", "labels", "series"}`; mermaid: raw Mermaid diagram text),
      that the harness auto-binds `label -> fig-<sha8>` and never clobbers a
      manual binding, and that a malformed/unsupported entry WARNs and is
      skipped rather than failing the build.
      Run: `uv run pytest tests/unit/test_agents_md_content.py`.

---

## Review Workload Forecast

Per-slice estimated diff size (implementation + tests), and PR-boundary
proposal ordered by dependency (design.md: "5-7 slices, 400-line budget risk:
HIGH"):

| # | Slice | Depends on | Est. lines (impl + tests) | Notes |
|---|-------|-----------|---------------------------|-------|
| 1 | Domain foundation (ports, `VisualSpec`, `normalize_svg`, `merge`/`merge_bindings`) | none | ~350 | Pure domain, safest to land first — everything else imports it |
| 2 | `ChartSvgRenderer` | 1 | ~380 | No external toolchain; includes the RED threat test |
| 3 | `MermaidSvgRenderer` + `resolve_mmdc` | 1 | ~350 | Optional toolchain; includes the RED threat test |
| 4 | `SvgRasterizerPort` + resvg adapter + `resolve_resvg` | 1 | ~300 | Optional toolchain; reuses existing dims port (no new port there) |
| 5 | `GenerateVisualsService` + stage wiring + auto-bind | 1, 2, 3, 4 | **~450 — OVER budget** | Largest slice: service logic (5.1–5.7) + domain/pipeline + application/pipeline + cli/_shared wiring (5.8–5.10) |
| 6 | `html_render` swap + E2E | 5 | ~330 | Includes the docx-characterization guard (6.2) and the E2E byte-identity proof (6.3) |
| 7 | doctor checks + pyproject + AGENTS.md | 3, 4 (tool_resolver additions) | ~150 | Lowest risk; can land any time after 3/4 |

**Total estimate: ~2,310 lines across 7 PRs.**

**Chained PRs: recommended.** Six of seven slices are near or over the
~400-line budget; Slice 5 alone forecasts ~450 lines and mixes two concerns
(service logic vs. composition-root/stage wiring). Per `delivery_strategy:
ask-on-risk`, the orchestrator MUST confirm before `sdd-apply`:

1. Land as exactly 7 chained PRs per the table above (accept Slice 5 running
   ~50 lines over budget), **or**
2. Split Slice 5 into **5a** (5.1–5.7, `GenerateVisualsService` alone,
   ~300 lines) and **5b** (5.8–5.10, pipeline/composition-root wiring,
   ~150 lines) — 8 PRs total, every PR under budget.

Dependency order is fixed regardless of the split decision: **1 → {2, 3, 4}
(parallelizable, all depend only on 1) → 5(a/b) → 6 → 7** (7 only needs 3/4's
`tool_resolver` additions, so it can land any time after those, in parallel
with 5/6 if desired).
