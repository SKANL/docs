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

## S4 — Assembly integration, degradation, determinism/estadia characterization — DONE

- [x] 4.1 RED: `tests/unit/application/test_figure_resolver.py` (new, 6
  cases per ADR-4/ADR-6): absent bindings file -> empty resolver; malformed
  bindings file -> empty resolver; existing file + non-null dims -> included
  as `BoundFigure` with absolute path; missing file -> excluded + WARN
  ("imagen no encontrada"); null dims -> excluded + WARN ("sin
  dimensiones"); unknown catalog id -> excluded + WARN. Confirmed failure:
  `ModuleNotFoundError: No module named 'docs.application.figure_resolver'`.
- [x] 4.2 GREEN: `src/docs/application/figure_resolver.py` (new) —
  `build_bound_figures_resolver(sections_dir, assets_dir)`: fail-open JSON
  reads of `figure-bindings.json`/`figure-catalog.json` (same pattern as
  `_read_prior_confirmed_roles`), joins by catalog id, validates per ADR-6
  (file exists under `assets_dir/figures/` AND non-null `width_px`/
  `height_px`), resolves the path uniformly as
  `Path(assets_dir)/"figures"/Path(origin_relative_path).name`. `tests/unit/application/test_figure_resolver.py`
  = 6 passed.
- [x] 4.3 RED: `tests/unit/application/test_section_markdown.py` (new — no
  prior coverage of `strip_frontmatter_to_temp` existed) — 4 cases: omitted
  `bound_figures` byte-identical to today; explicit `bound_figures=None`
  same; provided `bound_figures` forwarded to `number_and_resolve` (image
  markdown in output); unbound label with `bound_figures` given still
  resolves to text-only caption. Confirmed failure: `TypeError:
  strip_frontmatter_to_temp() got an unexpected keyword argument
  'bound_figures'` (1 passed, 3 failed — the 1 pre-existing-shape case
  already passed by definition).
- [x] 4.4 GREEN: `src/docs/application/section_markdown.py` —
  `strip_frontmatter_to_temp(sections, bound_figures=None)` forwards
  `bound_figures` to `number_and_resolve` unchanged. `tests/unit/application/test_section_markdown.py`
  = 4 passed.
- [x] 4.5 RED: `tests/integration/test_docx_assembly_service.py` — a bound
  `[[figure:label]]` (via `figure-bindings.json` fixture + a real
  `_solid_png` image under `assets_dir/figures/`) assembled `.docx` zip
  contains a `word/media/` entry (`test_build_embeds_bound_figure_and_leaves_unbound_label_text_only`);
  an unbound label in the same document produces no additional media entry
  and stays `Figura N.` text-only. Confirmed failure: `assert 0 == 1` (no
  media entry — wiring didn't exist yet).
- [x] 4.6 RED: same file — missing bound image file -> build completes, no
  crash, caption-only, WARN naming the label
  (`test_build_degrades_gracefully_when_bound_image_file_is_missing`);
  corrupt-but-present bound image -> same degrade+WARN outcome, mapped to
  the SAME signal the ingest layer already uses for a corrupted image (file
  present under `assets_dir/figures/`, but its catalog row carries null
  `width_px`/`height_px` because ingest's dimension read already failed on
  it — ADR-6 explicitly reuses that catalog signal instead of a new
  file-reopening port in the renderer, so this is the resolver's existing
  null-dims guard exercised against a present file, not new validation code)
  (`test_build_degrades_gracefully_for_corrupt_but_present_bound_image`);
  one degraded figure among several bound figures still embeds every other
  figure normally, 2 media entries out of 3 bound labels
  (`test_build_embeds_healthy_figures_when_one_bound_figure_among_several_is_degraded`).
  Confirmed failure: `assert 'WARN' in ''` / `assert 0 == 2` (wiring didn't
  exist yet, 4 failed total across 4.5+4.6).
- [x] 4.7 GREEN: wired `build_bound_figures_resolver` into
  `docx_assembly.py` (`DocxRendererAdapter._resolve_bound_figures` +
  `build`) and `html_render.py` (`HtmlRendererAdapter.build`): both build the
  `label -> BoundFigure` dict from `config["paths"]["sections_dir"]` +
  `config["paths"]["assets_dir"]` (fail-open to `{}` when either key is
  absent, e.g. minimal test-fixture configs with no figures — reproduces
  current behavior exactly, verified against 3.5's default-`None` guarantee
  end-to-end). `tests/integration/test_docx_assembly_service.py` +
  `tests/unit/application/test_html_render.py` = 50 passed (34 pre-existing
  docx_assembly + 4 new S4 + 12 html_render, all green).
- [x] 4.8 RED+GREEN together (characterization): extended
  `tests/integration/test_docx_zip_determinism.py` with
  `test_build_with_bound_figure_is_byte_identical_across_repeated_runs` —
  builds twice via the real `DocxRendererAdapter.build()` end-to-end path
  with a bound figure, asserts byte-identical output files and a real
  `word/media/` entry. Passed on first run (no separate RED needed per
  task — already green once 4.7 landed, confirming no new
  clock/random/path-embedding surface). `tests/integration/test_docx_zip_determinism.py`
  = 6 passed (5 pre-existing + 1 new).
- [x] 4.9 Regression gate: `tests/integration/test_technical_report_srs_acceptance.py`
  = 6 passed (estadia/reporte-estadia-tic characterization untouched). Full
  suite: **1373 passed, 0 failed, 7 skipped** (S3 baseline was 1358 passed;
  +15 net new S4 tests: 6 resolver + 4 section_markdown + 4 docx_assembly
  integration + 1 determinism). No regression.
- [x] 4.10 Full slice check green:
  `tests/integration/test_docx_assembly_service.py` +
  `tests/integration/test_docx_zip_determinism.py` +
  `tests/unit/application` = 169 passed. `ruff check` clean on all 8
  changed/new files.

### Deviation note: design ADR-6 residual-risk vs. tasks.md 4.6 "corrupt-but-present"

Design.md ADR-6 explicitly flags a corrupt-on-disk-after-ingest image as a
"residual (low) risk... noted, not built" for v1 (the resolver only reuses
the catalog's already-recorded dims as the readability signal, deliberately
NOT re-opening the file to re-validate it). tasks.md 4.6 asks for a
"corrupt-but-present" test case with the SAME degrade+WARN+no-crash outcome
as a missing file. These are reconciled, not in conflict: a corrupt image is
exactly the case ingest's existing `_read_image_dimensions` graceful
degradation already handles by recording `width_px=None`/`height_px=None`
in the catalog while still copying the raw (corrupt) bytes to
`assets_dir/figures/`. The resolver's existing null-dims guard (task 4.2,
built strictly per ADR-6, zero new code) therefore already produces exactly
the required degrade+WARN+no-crash outcome for a corrupt-but-present file —
confirmed empirically: real pandoc, given a garbage-byte "image" file with a
valid `width_px`/`height_px` catalog row, does NOT raise (embeds the broken
bytes as media and python-docx opens the result fine) — so ADR-6's residual
risk about pandoc's `check=True` crashing does not manifest for this pandoc
version either, and no additional validation code beyond ADR-6's two checks
was needed or added.

Commits (branch `feat/usfe-s4-assembly`, off main with S1+S2+S3 merged):
- (see `git log feat/usfe-s4-assembly` — resolver-builder + assembly wiring
  + degradation/determinism tests)

Touched only S4 files: `src/docs/application/figure_resolver.py` (new),
`src/docs/application/section_markdown.py` (modified),
`src/docs/application/docx_assembly.py` (modified),
`src/docs/application/html_render.py` (modified),
`tests/unit/application/test_figure_resolver.py` (new),
`tests/unit/application/test_section_markdown.py` (new),
`tests/integration/test_docx_assembly_service.py` (modified),
`tests/integration/test_docx_zip_determinism.py` (modified). No S1/S2/S3
files re-touched.

## Next

Task 5.1 (spec-delta merge into `openspec/specs/`) is deferred to the
archive phase per the orchestrator's instruction — not done in this apply
batch. All 4 code slices (S1-S4) are now complete and green.
