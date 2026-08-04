# Archive Report — on-demand-visual-generation

**Archived**: 2026-07-31 | **Merged**: main tip `6f9ebe8`, PRs #33–#40
(slices 1, 2, 3, 4, 5a, 5b, 6, 7) | **Verdict**: PASS (0 CRITICAL, 1
WARNING, 0 SUGGESTION)

## Slice PR Ledger

| PR | Slice | Content |
|----|-------|---------|
| #33 | S1 | Domain foundation: `VisualSpec`/`VisualRendererPort`/`SvgRasterizerPort` ports, `normalize_svg`, `figure_catalog.merge`, `figure_binding.merge_bindings` |
| #34 | S2 | `ChartSvgRenderer` (matplotlib Agg, declarative JSON spec, no external toolchain) |
| #35 | S3 | `MermaidSvgRenderer` (mmdc) + `resolve_mmdc` tool resolution |
| #36 | S4 | `ResvgRasterizerAdapter` (resvg) + `resolve_resvg` + reused PNG-dims port |
| #37 | S5a | `GenerateVisualsService` (registry dispatch, fail-open spec read, per-entry WARN+skip, catalog merge, auto-bind) |
| #38 | S5b | `generate-visuals` pipeline-stage wiring + composition-root (`cli/_shared.py`) wiring |
| #39 | S6 | `html_render` sibling `.png`→`.svg` swap + E2E byte-identity proof |
| #40 | S7 | `doctor` mmdc/resvg capability checks + `pyproject.toml` matplotlib dep + AGENTS.md authoring docs |

Slice 5 was split into 5a/5b (per the Review Workload Forecast's `ask-on-risk`
resolution) to keep every PR under the ~400-line review budget.

## Spec Reconciliation — Per File

### 1. `openspec/specs/document-visuals/spec.md` — NEW capability (CREATED)

Copied verbatim (already canonical form) from the delta. 5 requirements: Extensible
Visual-Renderer Registry, Agent-Authored Visual-Spec Declaration, Deterministic
SVG and Rasterized PNG per Visual, Catalog Registration and Auto-Bind, Graceful
Degradation on Missing Toolchain or Failed Visual. This raises the living
capability count from 11 to 12.

### 2. `openspec/specs/asset-management/spec.md` — MODIFIED

- **REPLACED** requirement "Deterministic Figure Catalog": `origin_kind` now
  documents a third value, `"generated"` (harness-rendered visual), alongside
  the pre-existing `standalone`/`pdf_render` values from the prior
  `smart-figure-embedding` reconciliation (archived 2026-07-31, same day) and
  the figure-catalog reconciliation. Added scenario "Catalog entry records
  origin_kind=generated for a harness-rendered visual". The "catalog is a
  deterministic INVENTORY / resolution owned by document-render" framing from
  the prior reconciliations was preserved verbatim (only the `origin_kind`
  sentence and inventory adjective — "ingested" → "ingested/generated" — were
  touched).
- **ADDED** requirement "Deterministic Figure-Catalog Merge": the pure
  `merge()` helper (union by `id`, no-clobber, re-sorted, safe-to-rerun).
  Inserted immediately after "Deterministic Figure Catalog" so the two
  catalog-shape requirements stay adjacent.
- **PRESERVED UNCHANGED**: Asset-Kind Validation, Asset Repository Port
  Generalization, Verbatim-Asset Pre-Ingest Routing, Pending-Placement Queue
  and Placement Manifest, Mechanical Role Filter for Figure Candidates,
  Stable Asset Path for Surviving Figure Candidates — none of these were
  touched by the merge (diff confirms only the two catalog requirements
  changed).

### 3. `openspec/specs/document-pipeline/spec.md` — MODIFIED

- **ADDED** requirement "Generate-Visuals Stage and Ordering": the
  `generate-visuals` stage, its ordering (strictly after `ingest`, strictly
  before `assemble`), format-agnosticism, and per-visual WARN+skip
  (`fail_fast=False`). Inserted after "Ingest Stage and Context-Curation
  Integration" (the closest-related existing requirement) and before
  "Reproducibility Boundary Principle".
- **PRESERVED UNCHANGED**: all 14 other pre-existing requirements
  (Data-Driven Format-Agnostic Stage Plan, Repository Port Segregation, CLI
  Composition Root Segregation, Dependency Declaration and Error-Handling
  Correctness, Application-Layer Test Coverage, Ingest Stage and
  Context-Curation Integration, Reproducibility Boundary Principle, Fail-Open
  Doctor for Optional Inputs, `doc status` Resumable Summary, Toolchain
  Validation with Degradable Optional Capabilities, Review Reads Rule Data
  From Template Config, Output-Format Selection, Template-Declared
  Review-Rules Checks, Build-Rules Guards Absent Paths, Document Workspace
  Creation Includes Ingest Inbox, Machine-Readable Gap Report) — none
  touched.

### 4. `openspec/specs/document-render/spec.md` — MODIFIED

- **ADDED** requirement "HTML Prefers Sibling SVG for a Bound Figure": HTML
  output prefers a same-stem sibling `.svg` over the catalog PNG when
  resolving a bound figure; docx continues to embed the PNG unconditionally
  (pandoc#9195); the swap does not alter dimensions/caption/number. Inserted
  at the end of the file, immediately after "Embedded-Image Build
  Determinism" — the requirement this one refines.
- **RECONCILED, NOT CLOBBERED**, with the `smart-figure-embedding` prior
  reconciliation: "Bound Figure Label Resolves to an Embedded Image",
  "Graceful Degradation on Missing or Corrupt Bound Image", and
  "Embedded-Image Build Determinism" (all landed by the prior sub-project)
  were left byte-for-byte untouched; this change's HTML-vs-docx format
  preference sits alongside them as a new requirement rather than editing
  their text.
- **PRESERVED UNCHANGED**: Renderer Port Abstraction, Format-Registry
  Resolution at Composition Root, Extensibility Proof via Test Fake,
  Config-Driven Assemble Stage Plan, Document-Order Figure/Table Numbering at
  Build Time, Evidence-Aware Review Precision, Deterministic HTML Renderer,
  Best-Effort PDF Renderer With Graceful Degradation.

## Review-Driven Fixes During Implementation

Three fixes surfaced during PR review and landed inside the slices above
(not as separate archive-time changes):

1. **aria-describedby determinism leak** — `normalize_svg`'s id-rewrite
   originally missed the `aria-describedby` attribute as an id-reference
   site, which could leave a non-deterministic id fragment in accessible SVG
   output; fixed by adding it to the attribute set normalized alongside
   `aria-labelledby`.
2. **Per-visual write-isolation** — an early version of
   `GenerateVisualsService`'s per-entry loop could let a partial write
   (SVG written, PNG rasterization failing) leave an inconsistent sibling
   pair; hardened so a failed rasterization/write is caught and WARNed
   without leaving an orphaned `.svg` referenced by neither catalog nor
   bindings.
3. **Shape-safe merge (commit `c31b3f2`)** — `figure_catalog.merge()` was
   hardened to fail open on malformed/shape-mismatched catalog JSON (missing
   keys, wrong types) rather than raising, matching the project's
   "never crash the build" convention for catalog/bindings I/O.

## New Dependencies

- **`matplotlib`** — hard new pip dependency (declared in `pyproject.toml`),
  used by `ChartSvgRenderer` (Agg backend, `savefig(format="svg")`). The
  only hard new pip dependency introduced by this change.
- **`mmdc` (Mermaid CLI)** and **`resvg`** — optional, PATH-resolved external
  toolchains (not pip/npm dependencies of this project). Their absence
  degrades gracefully: `MermaidSvgRenderer`/`ResvgRasterizerAdapter` raise a
  documented `RuntimeError` with install guidance, caught by
  `GenerateVisualsService`'s per-entry WARN+skip; `doctor` reports both as
  `required=False` capability checks (Slice 7).

## Final Test Evidence

`uv run pytest -q` → **1448 passed, 0 failed, 12 skipped** (unchanged by
this archive — no code was touched, only spec/doc reconciliation).

Skip reasons (all toolchain-gated, none newly introduced by archive):
mmdc/resvg absence gates 5 tests across
`test_generate_visuals_e2e.py`, `test_mermaid_svg_renderer_integration.py`,
`test_resvg_rasterizer_adapter_integration.py`; the remaining 7 skips are
pre-existing, unrelated to this capability.

Backward-compat characterization (`test_technical_report_srs_acceptance.py`
+ `test_documento_generico_acceptance.py`) held: 10 passed, 0 failed — no
`visual-specs.json` in either fixture doc, confirming the no-op guarantee.

## Capability Count

`docs/CLAUDE.md`'s "Specs & planning" section updated: **11 → 12**
capabilities. `document-visuals` inserted alphabetically between
`document-template` and `template-provisioning`.

## Open Item Carried Forward (from verify-report WARNING)

The proposal originally listed `agent-contract` as a Modified Capability for
`visual-specs.json`'s authoring schema. `sdd-spec` deliberately folded that
schema into `document-visuals` instead, documenting authoring guidance only
in `AGENTS.md` prose (task 7.3). This was a considered decision, not an
oversight, and is recorded here per the verify-report's recommendation: the
living `agent-contract` capability spec intentionally has no trace of
`visual-specs.json` — its authoring contract is owned by `document-visuals`
+ `AGENTS.md`, not `agent-contract`.

## Traceability

- Proposal: `openspec/changes/archive/2026-07-31-on-demand-visual-generation/proposal.md`
- Explore: `openspec/changes/archive/2026-07-31-on-demand-visual-generation/explore.md`
- Design: `openspec/changes/archive/2026-07-31-on-demand-visual-generation/design.md`
- Tasks: `openspec/changes/archive/2026-07-31-on-demand-visual-generation/tasks.md` (all 1.1–7.3 checked)
- Delta specs: `openspec/changes/archive/2026-07-31-on-demand-visual-generation/specs/{document-visuals,asset-management,document-pipeline,document-render}/spec.md`
- Apply progress: `openspec/changes/archive/2026-07-31-on-demand-visual-generation/apply-progress.md`
- Verify report: `openspec/changes/archive/2026-07-31-on-demand-visual-generation/verify-report.md`
