# Apply Progress: Smart Figure Embedding

Artifact store: hybrid (this file + Engram `sdd/smart-figure-embedding/apply-progress`).

## S1 — Domain: filter + fields — DONE

- [x] 1.1 RED `tests/unit/domain/test_figure_filter.py` (new, 7 cases per ADR-2/ADR-7)
- [x] 1.2 GREEN `src/docs/domain/figure_filter.py` (new) — `MIN_FIGURE_DIMENSION_PX=100` + `should_catalog_figure`
- [x] 1.3 RED extended `tests/unit/domain/test_figure_catalog.py` (+3 cases: defaults, round-trip, byte-identical w/ new fields)
- [x] 1.4 GREEN `src/docs/domain/figure_catalog.py` — added `source_role: str = ""`, `origin_kind: str = ""` to `FigureEntry`; `build()` emits both, additive only (existing keys unchanged/unreordered)
- [x] 1.5 Slice check green: `tests/unit/domain/test_figure_filter.py` + `tests/unit/domain/test_figure_catalog.py` = 15 passed. Full suite: 1342 passed, 0 failed, 7 skipped. `ruff check` clean on all 4 changed/new files.

Commits (branch `feat/usfe-s1-domain-filter`, off main `16294dc`):
- `cbe0516` feat(domain): add pure should_catalog_figure role/size filter
- `e327048` feat(domain): add source_role/origin_kind to FigureEntry

Touched only S1 files: `src/docs/domain/figure_filter.py` (new),
`src/docs/domain/figure_catalog.py` (modified),
`tests/unit/domain/test_figure_filter.py` (new),
`tests/unit/domain/test_figure_catalog.py` (modified). No S2/S3/S4 files
touched (`application/ingest.py`, `domain/figure_binding.py`,
`domain/cross_reference.py`, `application/section_markdown.py`,
`application/docx_assembly.py`, `application/html_render.py` all
untouched).

## S0 — Resolved (gated S2 fixtures) — DONE

- [x] 0.1 `assets_dir` at ingest AND assemble time is the SAME accessor:
  `config["paths"]["assets_dir"]` = `str(doc_root / "assets")`
  (`cli/_shared.py:_computed_paths:322`), populated once in
  `Deps.resolve_context` (`cli/_shared.py:201-219`) and reused by every
  command (`pipeline.py:stage_ingest:309` reads it the same way assemble's
  `docx_assembly.build`/`html_render.build` will in S4). No
  `AssetService.workspace.assets_dir` fallback needed. Recorded as a code
  comment at `ingest.py`'s `_build_figure_catalog` (S2's assets_dir usage
  site).
- [x] 0.2 Confirmed: `_build_figure_catalog` only ever handles (a) standalone
  loose images (`image_candidates` from `declared_assets`/
  `heuristic_candidates`) and (b) vector-PDF page-renders
  (`_render_vector_pdf_figures`) — no third arrival mode reaches this method
  in the current codebase. Embedded-raster-inside-PDF/DOCX stays deferred
  (design.md "Approved LEAN scope"). Noted as a code comment, no code
  change.

## S2 — Ingest wiring — DONE

- [x] 2.1 RED: `tests/integration/test_ingest_assets_figures.py` —
  `test_standalone_guia_role_image_excluded_from_figure_catalog` +
  `test_standalone_evidence_role_image_kept_with_source_role_recorded` (new)
- [x] 2.2 RED: same file —
  `test_standalone_survivor_copied_to_stable_path_atomically_and_origin_rewritten`
  (new)
- [x] 2.3 RED: same file —
  `test_vector_pdf_render_not_re_copied_by_standalone_copy_step` (new)
- [x] 2.4 RED: same file —
  `test_parent_pdf_confirmed_role_propagates_to_vector_page_renders` (new)
- [x] 2.5 RED: `tests/integration/test_ingest_determinism.py` —
  `test_figure_catalog_and_stable_path_assets_are_byte_identical_across_repeated_runs`
  (new)
- [x] 2.6 GREEN: `_build_figure_catalog` (`ingest.py`) — role resolution via
  new `_effective_role` helper (reuses `_read_prior_confirmed_roles`
  verbatim) + `should_catalog_figure` filter call, applied per standalone
  candidate after role/dims are known, before append/copy.
- [x] 2.7 GREEN: `_copy_asset` extended to temp-then-`os.replace` (atomic);
  new `_copy_standalone_figure` helper writes surviving standalone entries
  to `assets_dir/figures/fig-<sha8><ext>` and rewrites
  `origin_relative_path` via `dataclasses.replace` (frozen `FigureEntry`).
  `pdf_render` rows (`origin_kind="pdf_render"`) are never touched by this
  step — `_render_vector_pdf_figures` already wrote them to their own
  stable path.
- [x] 2.8 GREEN: `_render_vector_pdf_figures` now takes `confirmed_roles`
  and resolves role from the PARENT PDF's `entry["relative_path"]` (not the
  per-page render path) — a confirmed PDF role overrides raw `classify()`
  on every page-render row. Role-based drops short-circuit BEFORE
  `render_pages` is even called (never rendered, never copied); size-based
  drops apply per rendered page once real dims are known.
- [x] 2.9 Full slice check green:
  `test_ingest_assets_figures.py` + `test_ingest_determinism.py` +
  `test_ingest_service.py` = 44 passed. Sibling regression sweep:
  `tests/unit/application -k ingest` = 29 passed;
  `tests/integration -k ingest` = 82 passed. Full suite: **1348 passed, 0
  failed, 7 skipped** (S1 baseline was 1342 passed; +6 net new S2 tests).
  `ruff check` clean on `ingest.py` + both changed test files.

### Pre-existing test fixture conflicts resolved (not scope creep — a direct,
mechanical consequence of wiring the already-approved S1 filter)

Wiring `should_catalog_figure` for real exposed two latent conflicts between
existing fixtures and the new filter, both fixed forward (root-cause, not
weakening S1):

1. **Size filter vs. 1x1 test PNGs**: every pre-existing figure-catalog test
   used a 1x1 `_PIXEL_PNG` fixture; `MIN_FIGURE_DIMENSION_PX=100` now drops
   anything that small. Fixed by adding a `_solid_png(width, height)` test
   helper (same struct+zlib construction already used by
   `_malformed_but_pillow_openable_png`, no new dependency) and bumping
   `_FakeImageMetadata`'s fake dims from `(1, 1)` to `(200, 200)`. Affected:
   `test_figure_catalog_written_with_hash_and_dimensions`,
   `test_real_drop_cover_convention_asset_and_catalog_images_all_visible`,
   `test_image_metadata_crash_is_isolated_warns_and_still_catalogs_other_images`
   (dims/assertions updated, intent unchanged).
2. **Role filter vs. an incidental "guia" fixture folder**:
   `test_unproposable_image_is_cataloged_as_a_figure_not_queued_for_placement`
   used folder `images/guia/` — its actual purpose (placement-queue
   behavior) had nothing to do with role filtering, but "guia" folds to
   `normative` (`source_role.py`) and would now be silently excluded.
   Renamed the fixture folder to the lexicon-neutral `images/otros/` so the
   test again isolates the behavior it names.
3. **Declared-asset origin_relative_path rewrite**: `logo.png`
   (`inbox/assets/`) is BOTH a declared asset (routed verbatim to
   `assets_dir/logo.png`, unchanged Front F behavior) AND a standalone
   figure candidate — the latter now gets the ADR-3 stable-path rewrite,
   so `test_figure_catalog_includes_declared_asset_images` and the
   real-drop acceptance test now look the figure up by `sha256[:8]`
   instead of asserting the old literal `origin_relative_path`.

Commits (branch `feat/usfe-s2-ingest`, off main `0e6ae78` — S1 merged via PR #28):
- (see `git log feat/usfe-s2-ingest` — ingest wiring + fixture fixes)

Touched only S2 files: `src/docs/application/ingest.py` (modified),
`tests/integration/test_ingest_assets_figures.py` (modified),
`tests/integration/test_ingest_determinism.py` (modified). No S3/S4 files
touched (`domain/figure_binding.py`, `domain/cross_reference.py`,
`application/section_markdown.py`, `application/docx_assembly.py`,
`application/html_render.py` all untouched).

## S3 — Binding model + `number_and_resolve` embedding branch — DONE

- [x] 3.1 RED: `tests/unit/domain/test_figure_binding.py` (new) —
  `figure_width_attr` cases (None -> "", below-clamp -> `{width=<in>in}` at
  `ASSUMED_DPI=96` rounded to 2 decimals, above-clamp -> `{width=6.0in}`).
  Confirmed failure: `ModuleNotFoundError: No module named
  'docs.domain.figure_binding'`.
- [x] 3.2 RED: same file — `figure_image_markdown` cases (captioned ->
  `![Figura N. caption](path){width=...}`, empty caption -> rstripped
  `Figura N.`). Same RED as 3.1 (module didn't exist).
- [x] 3.3 GREEN: `src/docs/domain/figure_binding.py` (new) — frozen
  `BoundFigure` (`label`, `catalog_id`, `path`, `width_px`, `height_px`,
  `caption`), `ASSUMED_DPI=96`, `MAX_CONTENT_WIDTH_IN=6.0`,
  `figure_width_attr`, `figure_image_markdown` exactly per ADR-5. Pure, no
  I/O. `tests/unit/domain/test_figure_binding.py` = 5 passed.
- [x] 3.4 RED: extended `tests/unit/domain/test_cross_reference.py` — 3 new
  cases: bound `[[figure:label]]` -> image markdown
  (`test_bound_figure_label_is_replaced_by_image_markdown`); unbound label
  in the same bound_figures call -> unchanged `Figura N.` text
  (`test_unbound_figure_label_still_resolves_to_text_only_caption`);
  `[[table:]]`/`[[ref:]]` untouched by bound_figures
  (`test_bound_figures_does_not_affect_table_or_ref_markers`). Confirmed
  failure: `TypeError: number_and_resolve() got an unexpected keyword
  argument 'bound_figures'` (3 failed, 9 passed — the 9 include the
  regression-guard test below, which already passed pre-change by
  definition).
- [x] 3.5 RED (regression guard):
  `test_bound_figures_omitted_reproduces_todays_output_byte_for_byte` — every
  existing `number_and_resolve` call with `bound_figures` omitted stays
  byte-identical. Verified passing both before AND after 3.6 (no diff at any
  point — a real regression guard, not a fixture update).
- [x] 3.6 GREEN: `src/docs/domain/cross_reference.py` — added
  `bound_figures: dict[str, BoundFigure] | None = None` param to
  `number_and_resolve`; new `_figure_sub` closure in `_rewrite`: when
  `bound_figures is not None and label in bound_figures`, emits
  `figure_image_markdown(number, bound_figures[label])`, else the unchanged
  `Figura N.` text. `[[table:]]`/`[[ref:]]` paths untouched. Domain->domain
  import of `BoundFigure`/`figure_image_markdown` from `figure_binding.py`
  (allowed per hexagonal rules — both pure `domain/`).
- [x] 3.7 Full slice check green:
  `tests/unit/domain/test_figure_binding.py` +
  `tests/unit/domain/test_cross_reference.py` = 17 passed. Full suite:
  **1358 passed, 0 failed, 7 skipped** (S2 baseline was 1348 passed; +10 net
  new/changed assertions across 9 new test functions — 5 in
  `test_figure_binding.py`, 4 in `test_cross_reference.py`). `ruff check`
  clean on all 4 changed/new files
  (`src/docs/domain/figure_binding.py`,
  `src/docs/domain/cross_reference.py`,
  `tests/unit/domain/test_figure_binding.py`,
  `tests/unit/domain/test_cross_reference.py`).

Commits (branch `feat/usfe-s3-binding`, off main with S1+S2 merged):
- (see `git log feat/usfe-s3-binding` — binding model + cross_reference
  embedding branch)

Touched only S3 files: `src/docs/domain/figure_binding.py` (new),
`src/docs/domain/cross_reference.py` (modified),
`tests/unit/domain/test_figure_binding.py` (new),
`tests/unit/domain/test_cross_reference.py` (modified). No S4 files touched
(`application/section_markdown.py`, `application/docx_assembly.py`,
`application/html_render.py` all untouched); no S1/S2 files re-touched.

## Next

S4 — assembly integration, degradation, determinism/estadia
characterization (tasks 4.1–4.10) — not started. Depends on S2's real
ingest-produced catalog/asset rows AND S3's embedding branch together.
