# Verification Report — on-demand-visual-generation

**Change**: on-demand-visual-generation | **Mode**: full artifacts (proposal+design+tasks+4 spec deltas) | **Merged**: main tip 6f9ebe8, PRs #33-#40 (slices 1,2,3,4,5a,5b,6,7)

## Test Evidence

`uv run pytest -q` → **1448 passed, 0 failed, 12 skipped**.

Skip reasons (verified via `-rs`, all clean, correctly toolchain-gated):
- `test_generate_visuals_e2e.py:119` mmdc and/or resvg not installed (1)
- `test_mermaid_svg_renderer_integration.py:19,29` mmdc not installed (2)
- `test_resvg_rasterizer_adapter_integration.py:27,43` resvg not installed (2)
- (7 more skips elsewhere in the suite, pre-existing to other capabilities, unaffected)

Backward-compat characterization: `test_technical_report_srs_acceptance.py` + `test_documento_generico_acceptance.py` → 10 passed, 0 failed (no `visual-specs.json` in either fixture doc → byte-identical no-op holds).

## Spec Conformance (4 delta files)

### 1. `document-visuals` (NEW capability, 5 requirements)

| Requirement | Implementing symbol | Covering test |
|---|---|---|
| Extensible Visual-Renderer Registry | `domain/ports/visual_renderer_port.py` (VisualSpec, VisualRendererPort Protocol); `GenerateVisualsService.visual_renderers` dispatch by `type`; unregistered type WARN+skip in `_render_one` | `test_registry_dispatch_by_type`, `test_unregistered_type_warns_and_skips` |
| Agent-Authored Visual-Spec Declaration | `_read_specs_fail_open` (absent/malformed → `[]`), `_parse_spec` (WARN+skip missing field) | `test_missing_visual_specs_file_is_noop`, `test_malformed_entry_warns_naming_missing_field_others_still_process` |
| Deterministic SVG+PNG per Visual | `domain/svg_normalize.normalize_svg` + renderer-side determinism knobs (`svg.hashsalt`, `svg.fonttype=none`, pinned font) | `test_svg_normalize.py`, `test_render_plus_normalize_svg_is_byte_identical_across_two_runs` |
| Catalog Registration and Auto-Bind | `_render_one` builds `FigureEntry(origin_kind="generated", ...)`; `generate()` → `figure_catalog.merge` + `figure_binding.merge_bindings`, no-clobber WARN | `test_well_formed_entry_writes_sibling_svg_and_png_with_shared_stem`, `test_auto_binds_label_to_generated_id_no_clobber_warns_on_collision` |
| Graceful Degradation | per-entry `try/except Exception` at renderer/rasterizer/write layers; `generate()` never raises | `test_renderer_exception_and_missing_toolchain_warn_skip_others_continue`, `test_write_failure_warns_and_skips_never_raises` |

### 2. `asset-management` (MODIFIED)

`origin_kind="generated"` confirmed in `generate_visuals.py:236-244`. Pure `merge()` in `domain/figure_catalog.py` (union by id, re-sort, no-clobber). Covered: `test_merge_preserves_all_entries_no_clobber`, `test_merge_is_resorted_and_deterministic`, `test_merge_safe_to_rerun`, plus shape-safety hardening (fix commit `c31b3f2`).

### 3. `document-pipeline` (MODIFIED)

`domain/pipeline.py:_GENERATE_VISUALS = [("generate-visuals", False)]` prepended before assemble stages in both `"assemble"` and `"all"` branches (fail_fast=False). `application/pipeline.py:stage_generate_visuals` always returns `ok=True`. Covered: `test_generate_visuals_runs_after_ingest_before_assemble_in_all`, `test_stage_generate_visuals_is_wired_and_never_fail_fast`.

### 4. `document-render` (MODIFIED)

`html_render.py:_prefer_sibling_svg` swaps `.png`→sibling `.svg` via `dataclasses.replace`, all other fields preserved; called after `build_bound_figures_resolver`, before `strip_frontmatter_to_temp`. `docx_assembly.py` untouched. Covered: `test_html_render_svg_swap.py` (2 cases), `test_docx_always_embeds_png_even_with_sibling_svg` (characterization guard), E2E `test_chart_only_pipeline_e2e_docx_png_html_svg` (hermetic, no skipif).

## Tasks Completeness

All tasks 1.1–7.3 (slices 1,2,3,4,5a,5b,6,7) ticked `[x]` in `tasks.md`. Spot-checked against code (not just checkboxes): `svg_normalize.py`, `generate_visuals.py`, `chart_svg_renderer.py`, `mermaid_svg_renderer.py`, `resvg_rasterizer_adapter.py`, `domain/pipeline.py`, `application/pipeline.py`, `html_render.py`, `application/doctor.py` (mmdc/resvg checks, `required=False`) — all match tasks.md and design.md decisions.

**Spec-delta merge correctly deferred**: `openspec/specs/` contains only the 11 pre-existing capabilities. `document-visuals` and the origin_kind=generated/generate-visuals-stage/sibling-svg deltas are ABSENT from living specs — confirms deferral to `sdd-archive`.

## Security (Threat Matrix)

- `chart_svg_renderer.py`: `spec.source` parsed via `json.loads` ONLY, never `eval`/`exec`. Covered: `test_python_looking_source_text_renders_as_inert_data` (mocks + asserts never invoked).
- `mermaid_svg_renderer.py`: source written to temp `.mmd`, `mmdc` invoked with a fixed list arg, never `shell=True`. Covered: `test_source_with_shell_metacharacters_never_reaches_a_shell`.
- `resvg_rasterizer_adapter.py`: fixed arg list, no `shell=True`. Covered: `test_rasterize_never_uses_shell`.

## Issues

**CRITICAL**: none.

**WARNING** (1): The proposal listed `agent-contract` as a Modified Capability for `visual-specs.json`'s schema, but sdd-spec deliberately folded the schema into `document-visuals` instead and only documented authoring in `AGENTS.md` prose (task 7.3, confirmed at `AGENTS.md:286`). Recorded decision, not an oversight — but the living `agent-contract` capability spec has no trace of `visual-specs.json` after archive. Recommend confirming at archive time whether this is acceptable.

**SUGGESTION**: none.

## Verdict: PASS (0 CRITICAL, 1 WARNING, 0 SUGGESTION)

Real pytest count: **1448 passed, 0 failed, 12 skipped**.
