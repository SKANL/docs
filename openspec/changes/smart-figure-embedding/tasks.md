# Tasks: Smart Figure Embedding

Delivery strategy: `ask-on-risk`. Artifact store: hybrid (this file +
Engram `sdd/smart-figure-embedding/tasks`).

Strict TDD on every task below: the failing test is written and run (red)
BEFORE any implementation line. No task is "done" until its test list is
green and no unrelated test regressed. Hexagonal boundaries: nothing in
`domain/` imports `application/`/`infrastructure/`; nothing in
`application/` imports `infrastructure/` directly for this feature (reuses
existing ports/adapters only). Determinism: no new wall-clock/random data on
any path; `bound_figures=None` (or a resolver built from an empty/absent
bindings file) MUST reproduce today's output byte-for-byte.

Slice order is a hard dependency chain: **S1 -> S2 -> S3 -> S4**. S2 needs
S1's `FigureEntry` fields + `figure_filter`; S3 needs S1's fields (catalog
read) and is independent of S2's ingest wiring but both feed S4; S4 needs
S2 (real catalog+asset rows to bind) and S3 (the embedding branch) together.

---

## S0 — Resolve open questions (blocking prerequisite, before S2/S4 code)

- [ ] **0.1** Confirm `assets_dir` source at assemble time. Read
  `src/docs/cli/_shared.py` around the composition root (`Deps`, `~:322`
  per design) and trace how `docx_assembly.build` / `html_render.build`
  currently receive `config`/`assets_dir`. Confirm
  `config["paths"]["assets_dir"]` is populated in the assemble config path,
  or identify the actual accessor (e.g. `AssetService.workspace.assets_dir`)
  to use in S3/S4's resolver-builder. Record the resolved answer as a code
  comment at the resolver-builder call site (S3.4/S4.1) — no separate doc.
- [ ] **0.2** Verify how a "ficha" (figure candidate) arrives in practice:
  confirm today's `inbox/` intake only ever presents it as (a) a standalone
  loose image file, or (b) a page inside a vector PDF (the two catalog
  sources `_build_figure_catalog` already handles). If a third arrival mode
  (raster embedded inside a PDF/DOCX) is observed in a real workspace,
  confirm it is out of LEAN scope (deferred embedded-raster extraction per
  design.md Approved LEAN scope) and does not silently reach the mechanical
  filter/catalog as a false candidate. No code change expected; this gates
  S2 test fixture choices (only use standalone-image and vector-PDF-render
  fixtures).

---

## S1 — Domain: filter + fields

*Files*: `src/docs/domain/figure_filter.py` (NEW),
`src/docs/domain/figure_catalog.py` (MODIFIED).
*Tests*: `tests/unit/domain/test_figure_filter.py` (NEW),
`tests/unit/domain/test_figure_catalog.py` (MODIFIED).
*Spec refs*: asset-management "Deterministic Figure Catalog" (MODIFIED),
asset-management "Mechanical Role Filter for Figure Candidates" (ADDED).

- [x] **1.1** RED: `tests/unit/domain/test_figure_filter.py` — write
  `should_catalog_figure` behavior tests per ADR-2/ADR-7:
  - `source_role="normative"` (guia-folded) -> `False`
  - `source_role="example"` -> `False`
  - `source_role="evidence"` -> `True`
  - `source_role="unknown"` -> `True` (fail-open)
  - dims present, `max(width_px, height_px) < MIN_FIGURE_DIMENSION_PX` ->
    `False` (sub-threshold junk)
  - dims present, at/above threshold -> `True`
  - `width_px`/`height_px` both `None` -> `True` (fail-open, can't judge)
  Run and confirm every case fails (module doesn't exist yet).
- [x] **1.2** GREEN: implement `domain/figure_filter.py` — pure
  `MIN_FIGURE_DIMENSION_PX = 100` constant + `should_catalog_figure(source_role, width_px, height_px) -> bool`
  exactly per ADR-2 pseudocode. No I/O, no imports outside stdlib/domain.
- [x] **1.3** RED: extend `tests/unit/domain/test_figure_catalog.py` —
  `FigureEntry` accepts `source_role: str` and `origin_kind: str`
  (default-valued `""` each, per ADR-1); `build()` round-trips both keys
  into each emitted row; a catalog built twice from identical
  `FigureEntry` rows (including these two new fields) is byte-identical
  (dict/JSON key order stable). Run and confirm failure (fields don't
  exist yet).
- [x] **1.4** GREEN: add `source_role: str = ""` and `origin_kind: str = ""`
  to the frozen `FigureEntry` dataclass (`figure_catalog.py:8`) and have
  `build()` (`figure_catalog.py:16`) emit both keys per row, additive only
  — do not reorder/remove existing keys (`sha256`, `width_px`, `height_px`,
  `origin_relative_path`, `caption`).
- [x] **1.5** Full slice check: `uv run pytest tests/unit/domain/test_figure_filter.py tests/unit/domain/test_figure_catalog.py -q` green; no other domain test touched.

---

## S2 — Ingest wiring: role resolution, filter, stable-path copy, role propagation

*Files*: `src/docs/application/ingest.py` (MODIFIED only — no new file).
*Tests*: `tests/unit/application/test_ingest_service.py` and/or
`tests/integration/test_ingest_assets_figures.py` (MODIFIED — reuse
existing figure-catalog ingest fixtures rather than inventing a parallel
suite).
*Spec refs*: document-pipeline "Ingest Stage and Context-Curation
Integration" (MODIFIED), asset-management "Mechanical Role Filter for
Figure Candidates" (ADDED), asset-management "Stable Asset Path for
Surviving Figure Candidates" (ADDED).

- [ ] **2.1** RED: extend `tests/integration/test_ingest_assets_figures.py`
  — a standalone image whose originating source resolves to
  `example`/`normative` (guia) role is EXCLUDED from `figure-catalog.json`
  (no entry) per ADR-1/ADR-2 role-resolution rule; a standalone
  `evidence`-role image IS kept with `source_role="evidence"` recorded.
  Run and confirm failure (filter not wired yet).
- [ ] **2.2** RED: same file — a surviving standalone candidate is copied to
  `assets_dir/figures/fig-<sha8><ext>` (sha8 = `sha256[:8]`, ext =
  lower-cased origin suffix) via an ATOMIC write (assert no `.tmp`/partial
  leftover on a simulated interrupt, or at minimum assert the final file
  exists and content matches); its catalog `origin_relative_path` is
  rewritten to `assets/figures/fig-<sha8><ext>` (POSIX). Confirm failure.
- [ ] **2.3** RED: same file — a vector-PDF-rendered figure
  (`origin_kind="pdf_render"`) is NOT re-copied by the new standalone-copy
  step (its `_render_vector_pdf_figures` output path is untouched, no
  duplicate file). Confirm failure (fields/branch don't exist yet).
- [ ] **2.4** RED: same file — a parent PDF with a CONFIRMED role in
  `_classification-queue.json` propagates that confirmed role to every
  vector-page-render row's `source_role`, overriding raw `classify()` on
  the render itself (the ADR-1 divergence case). A standalone image with
  no queue entry falls through to raw `classify(rel)`. Confirm failure.
- [ ] **2.5** RED: same file (or `test_ingest_determinism.py`) — running
  ingest twice on the same inbox produces byte-identical
  `figure-catalog.json` AND byte-identical `assets_dir/figures/` contents
  (asset-management "Stable-path copy is deterministic" scenario;
  document-pipeline "Ingest excludes reference-role images and copies
  survivors deterministically" scenario). Confirm failure or pre-existing
  pass-by-accident is re-verified as a REAL assertion tied to the new
  fields.
- [ ] **2.6** GREEN: in `_build_figure_catalog` (`ingest.py:868`), for each
  candidate (both catalog sources) compute `effective_role` via the ADR-1
  lookup (`confirmed_roles.get(rel)` if present/valid else
  `classify(rel).role`) — reuse `_read_prior_confirmed_roles` verbatim, no
  new queue plumbing. Apply `should_catalog_figure(source_role, width_px,
  height_px)` per candidate AFTER role/dims are computed and BEFORE the
  entry is appended / before the stable-path copy. Dropped candidates never
  enter the catalog and are never copied.
- [ ] **2.7** GREEN: extend `_copy_asset` (`ingest.py:847`) to
  temp-then-`os.replace` (matching `atomic_ingest_write.py` /
  `filesystem_ingest_artifact_writer.py` convention). Add the standalone
  survivor copy step: deterministic name `fig-<sha8><ext>`, write into
  `assets_dir/figures/`, then rewrite that row's `origin_relative_path` to
  `assets/figures/fig-<sha8><ext>` (POSIX) — only for `origin_kind ==
  "standalone"`; skip rows already written by `_render_vector_pdf_figures`
  (`origin_kind == "pdf_render"`, `ingest.py:964`, already stable-pathed).
- [ ] **2.8** GREEN: for the vector-PDF-render source, resolve `rel` as the
  **parent PDF's** inbox `relative_path` (in scope at
  `_render_vector_pdf_figures`, `ingest.py:948,963`) when doing the ADR-1
  role lookup, so a human-confirmed PDF role wins over raw `classify()` on
  the render row.
- [ ] **2.9** Full slice check:
  `uv run pytest tests/integration/test_ingest_assets_figures.py tests/integration/test_ingest_determinism.py tests/unit/application/test_ingest_service.py -q`
  green; also run
  `uv run pytest tests/unit/application -q tests/integration -k ingest -q`
  to catch any sibling ingest regression from the `_copy_asset` signature
  change.

---

## S3 — Binding model + `number_and_resolve` embedding branch

*Files*: `src/docs/domain/figure_binding.py` (NEW),
`src/docs/domain/cross_reference.py` (MODIFIED).
*Tests*: `tests/unit/domain/test_figure_binding.py` (NEW),
`tests/unit/domain/test_cross_reference.py` (MODIFIED).
*Spec refs*: document-render "Bound Figure Label Resolves to an Embedded
Image" (ADDED, scenarios "Bound label embeds the image" / "Embedding does
not alter numbering/cross-reference resolution").

- [ ] **3.1** RED: `tests/unit/domain/test_figure_binding.py` —
  `figure_width_attr`: `None` width -> `""`; a width below the
  `MAX_CONTENT_WIDTH_IN` clamp -> `f"{{width={inches}in}}"` at
  `ASSUMED_DPI=96` px/in, rounded to 2 decimals; a width that would exceed
  `MAX_CONTENT_WIDTH_IN=6.0` -> clamped to `6.0in`. Confirm failure (module
  doesn't exist).
- [ ] **3.2** RED: same file — `figure_image_markdown(number, fig)` emits
  `![Figura {N}. {caption}]({path}){width=...}` for a `BoundFigure` with a
  caption; an empty/falsy caption produces the trailing-space-stripped
  `Figura {N}.` alt text (`.rstrip()` behavior per ADR-5). Confirm failure.
- [ ] **3.3** GREEN: implement `domain/figure_binding.py` — frozen
  `BoundFigure` dataclass (`label`, `catalog_id`, `path`, `width_px`,
  `height_px`, `caption`), `ASSUMED_DPI = 96`,
  `MAX_CONTENT_WIDTH_IN = 6.0`, `figure_width_attr`,
  `figure_image_markdown` exactly per ADR-5 pseudocode. Pure, no I/O.
- [ ] **3.4** RED: extend `tests/unit/domain/test_cross_reference.py` —
  `number_and_resolve(..., bound_figures={"label": bound_figure})`: a
  `[[figure:label]]` where `label` IS in `bound_figures` is replaced by
  `figure_image_markdown(number, fig)` (image markdown, not bare text); a
  `[[figure:other-label]]` where `other-label` is NOT in `bound_figures`
  still resolves to the unchanged `Figura N.` text; `[[table:...]]` /
  `[[ref:...]]` labels are untouched by `bound_figures` regardless of
  content. Confirm failure (param doesn't exist yet).
- [ ] **3.5** RED: same file — REGRESSION GUARD: every existing
  `number_and_resolve` call in the current test file, run with
  `bound_figures` OMITTED (default `None`), produces byte-identical output
  to pre-change behavior (backward-compat default, design.md "Embedding
  does not alter numbering/cross-reference resolution" + proposal rollback
  guarantee). This must already pass once 3.6 lands with `None` as default
  — treat any diff here as a hard regression, not an update-the-fixture
  situation.
- [ ] **3.6** GREEN: add `bound_figures: dict[str, BoundFigure] | None =
  None` param to `number_and_resolve` (`cross_reference.py:15`); in
  `_rewrite`, when the label kind is `figure` and
  `bound_figures is not None and label in bound_figures`, emit
  `figure_image_markdown(number, bound_figures[label])` instead of the
  text-only `Figura N.` path. All other label kinds/paths unchanged.
- [ ] **3.7** Full slice check:
  `uv run pytest tests/unit/domain/test_figure_binding.py tests/unit/domain/test_cross_reference.py -q`
  green.

---

## S4 — Assembly integration, degradation, determinism/estadia characterization

*Files*: `src/docs/application/section_markdown.py` (MODIFIED),
`src/docs/application/docx_assembly.py` (MODIFIED),
`src/docs/application/html_render.py` (MODIFIED).
*Tests*: `tests/unit/application/test_ingest_service.py`-adjacent unit test
for the resolver-builder (new small unit test module or extend an existing
`application` test file for `docx_assembly`/`html_render` if one exists),
`tests/integration/test_docx_assembly_service.py` (MODIFIED),
`tests/integration/test_docx_zip_determinism.py` (MODIFIED),
`tests/integration/test_technical_report_srs_acceptance.py` (regression
run, characterization/estadia fixture — MUST stay green, no behavior
edits expected).
*Spec refs*: document-render "Bound Figure Label Resolves to an Embedded
Image" (ADDED), document-render "Graceful Degradation on Missing or
Corrupt Bound Image" (ADDED), document-render "Embedded-Image Build
Determinism" (ADDED).

- [ ] **4.1** RED: unit test for the application-layer resolver-builder
  (label -> `BoundFigure`, joining `figure-catalog.json` +
  `figure-bindings.json`) — per ADR-4/ADR-6:
  - absent/malformed `figure-bindings.json` -> empty resolver (fail-open,
    same pattern as `_read_prior_confirmed_roles`)
  - a binding whose catalog id resolves to a file that EXISTS under
    `assets_dir/figures/` AND has non-null `width_px`/`height_px` ->
    included in the resolver as a `BoundFigure` with an absolute `path`
  - a binding whose file is MISSING -> excluded from the resolver + a WARN
    naming the label/catalog-id/cause is emitted (assert on captured
    stderr/log or the WARN-collection mechanism this codebase already uses
    for ingest WARNs)
  - a binding whose catalog row has null `width_px`/`height_px` -> excluded
    + WARN ("sin dimensiones")
  Confirm failure (builder doesn't exist yet).
- [ ] **4.2** GREEN: implement the resolver-builder in `application/`
  (co-located with or adjacent to `docx_assembly.build`/`html_render.build`
  — do not put this in `domain/`, it does file-existence I/O). Read
  `sections/figure-catalog.json` + `sections/figure-bindings.json` (same
  `sections_dir`), join by catalog id, validate per ADR-6, resolve the
  file path via `Path(assets_dir) / "figures" / Path(origin_relative_path).name`
  (uniform for both `origin_kind`s per ADR-3), return `dict[str,
  BoundFigure]`. Resolve the `assets_dir` source per task 0.1's finding.
- [ ] **4.3** RED: `strip_frontmatter_to_temp` (`section_markdown.py:27`) —
  extend its test coverage (none exists today per codegraph — this is new
  coverage, not just new cases) to assert the `bound_figures` param, when
  provided, is forwarded to `number_and_resolve` unchanged; when omitted,
  output is byte-identical to current behavior. Confirm failure (param
  doesn't exist).
- [ ] **4.4** GREEN: add `bound_figures: dict[str, BoundFigure] | None =
  None` to `strip_frontmatter_to_temp`, forward to `number_and_resolve`.
- [ ] **4.5** RED: `tests/integration/test_docx_assembly_service.py` — a
  section with a `[[figure:label]]` bound (via a `figure-bindings.json`
  fixture + a real image fixture under `assets_dir/figures/`) produces an
  assembled `.docx` whose zip contains a `word/media/` entry for that image
  (assert via zip inspection, not just markdown intermediate); an UNbound
  label in the same document produces NO new `word/media/` entry and the
  text-only `Figura N.` caption. Confirm failure (wiring doesn't exist).
- [ ] **4.6** RED: same file — missing bound image file -> build completes
  (no crash), caption/number still resolve, no image embedded for that
  figure, output includes a WARN naming the label/file; corrupt-but-present
  image file -> same degrade-and-WARN outcome, build still completes;
  a document with ONE degraded figure among several bound figures embeds
  every other figure normally (asset-management/document-render "One
  degraded figure does not affect other figures"). Confirm failure.
- [ ] **4.7** GREEN: wire the resolver-builder (4.2) into
  `docx_assembly.build` (`docx_assembly.py:93`) and `html_render.build`
  (`html_render.py:60`): build the `label -> BoundFigure` dict from
  catalog+bindings+assets_dir, pass to `strip_frontmatter_to_temp`. Passing
  nothing (no bindings file / empty catalog) reproduces current behavior —
  verify against 3.5's default-`None` guarantee end-to-end.
- [ ] **4.8** RED + GREEN together (characterization, not new behavior):
  extend `tests/integration/test_docx_zip_determinism.py` with a
  bound-figure fixture case — build twice, assert byte-identical output
  files (document-render "Embedded build is byte-identical across runs").
  This MUST already pass once 4.7 is correct, since no new
  clock/random/path-embedding surface is introduced (ADR-5 "Path in
  markdown" — absolute path is pandoc's read handle only, never enters
  output bytes); treat a failure here as a real determinism bug, not a
  fixture issue.
- [ ] **4.9** Regression gate (no code change expected): run
  `uv run pytest tests/integration/test_technical_report_srs_acceptance.py -q`
  and the full suite
  (`uv run pytest -q`) to confirm the estadia/reporte-estadia-tic
  characterization fixtures and every pre-existing test stay green with
  `bound_figures` unused (default path). Any regression here blocks the
  slice — fix forward in S4, do not weaken S1-S3 to compensate.
- [ ] **4.10** Full slice check:
  `uv run pytest tests/integration/test_docx_assembly_service.py tests/integration/test_docx_zip_determinism.py tests/unit/application -q`
  green.

---

## Spec-delta merge (apply-time, after S4 is green)

- [ ] **5.1** Merge the three delta spec files under
  `openspec/changes/smart-figure-embedding/specs/` into
  `openspec/specs/asset-management/spec.md`,
  `openspec/specs/document-render/spec.md`, and
  `openspec/specs/document-pipeline/spec.md`:
  - `asset-management`: replace "Deterministic Figure Catalog" with the
    MODIFIED version; add "Mechanical Role Filter for Figure Candidates"
    and "Stable Asset Path for Surviving Figure Candidates" as new
    requirements.
  - `document-render`: add "Bound Figure Label Resolves to an Embedded
    Image", "Graceful Degradation on Missing or Corrupt Bound Image", and
    "Embedded-Image Build Determinism" as new requirements.
  - `document-pipeline`: replace "Ingest Stage and Context-Curation
    Integration" with the MODIFIED version (adds the role-filter +
    stable-path-copy scenario).
  This is a mechanical text merge (delta -> living spec), no wording
  changes beyond removing the `(Previously: ...)` provenance notes per this
  project's normal archive convention — confirm against how the last
  merged change (`archive/2026-07-30-universal-schema-harness`) formatted
  its merge before doing this one, for consistency.

---

## Review Workload Forecast

| Slice | Files touched | Forecast (design ADR-7) | Nature |
|-------|---------------|--------------------------|--------|
| S1 | `domain/figure_filter.py` (new), `domain/figure_catalog.py` | ~120 lines | pure domain, new file + small dataclass addition |
| S2 | `application/ingest.py` | ~250 lines | ingest wiring: role resolution, filter call site, atomic stable-path copy, role propagation |
| S3 | `domain/figure_binding.py` (new), `domain/cross_reference.py` | ~200 lines | pure domain, new file + one new optional param on an existing pure function |
| S4 | `application/section_markdown.py`, `application/docx_assembly.py`, `application/html_render.py` | ~300 lines | resolver-builder (new, I/O) + wiring into two assembly entry points + degradation/determinism integration tests |
| **Total** | 4 slices, 7 source files (2 new, 5 modified) | **~870 lines** | tests+code combined per design.md |

- **No single slice exceeds the 400-line single-PR review budget** (largest
  is S4 at ~300).
- **The total (~870) exceeds the 400-line single-PR budget**, so a single
  combined PR is NOT recommended.
- **Chained PRs recommended**: one PR per slice, strictly ordered
  `S1 -> S2 -> S3 -> S4`, matching the hard dependency chain (S2 needs S1's
  `FigureEntry` fields + `figure_filter`; S3 needs S1's fields for catalog
  reads and is otherwise independent of S2 but both feed S4; S4 needs S2's
  real ingest-produced catalog/asset rows AND S3's embedding branch
  together). Each PR lands and passes its own full-suite regression gate
  (S1.5 / S2.9 / S3.7 / S4.9-4.10) before the next slice starts, so a
  reviewer never has to hold more than ~300 lines of new logic in view at
  once, and a bad slice is caught before it compounds into the next one's
  fixtures.
- **`delivery_strategy: ask-on-risk`**: this chaining decision (4 sequential
  PRs vs. any other grouping) is a judgment call with a real tradeoff
  (review latency of 4 rounds vs. a single ~870-line review that breaks the
  400-line budget) — the orchestrator MUST confirm the chaining decision
  with the user before `sdd-apply` starts creating branches/PRs.
