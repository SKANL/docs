# Archive Report: smart-figure-embedding

**Change**: smart-figure-embedding | **Archived**: 2026-07-31 | **Merge Tip**: 23d4290 (PR #31)

## Executive Summary

The smart-figure-embedding change is complete and archived. All 4 implementation slices (S1-S4) landed successfully across PRs #28-#31, with 2 post-merge hardening commits. 3 capabilities (asset-management, document-render, document-pipeline) were modified with 6 total requirements (1 MODIFIED, 2 ADDED in asset-management; 3 ADDED in document-render; 1 MODIFIED in document-pipeline). Verification passed; test suite: 1376 passed / 0 failed / 7 skipped. Specs merged into living `openspec/specs/` without conflict and without clobbering any unrelated requirement. No new capabilities created; the "11 capabilities" count remains correct.

## Spec Reconciliation Summary

### asset-management/spec.md

**MODIFIED**:
- **Deterministic Figure Catalog** (requirement name unchanged): the merge added `source_role` and `origin_kind` recording to the catalog-entry fields, documenting the mechanically classified provenance role (evidence vs. guia/example/reference) and whether the entry originated from a standalone image or a rendered PDF page. The living spec's PR #27 reconciliation (catalog = deterministic INVENTORY; figure-label resolution to captions/numbers is owned by the document-render capability's symbolic-label mechanism, not the catalog) was read first and preserved verbatim in framing — the merged requirement text still states the catalog is an inventory and does not reintroduce catalog-identifier resolution. Only the new source_role/origin_kind recording behavior was folded in as an additive field on catalog entries.

**ADDED**:
- **Mechanical Role Filter for Figure Candidates**: excludes example/reference-role (`guia`) images, keeps evidence-role and user-supplied images. Filter is mechanical (no agent judgment about relevance/placement/caption required). 3 scenarios: guia excluded, evidence kept, user-supplied kept.
- **Stable Asset Path for Surviving Figure Candidates**: survivors copied to `assets_dir/figures/` at ingest time (deterministic, atomic). 3 scenarios: survivor copied, excluded not copied, copy is deterministic.

### document-render/spec.md

**ADDED** (3 requirements, appended at end):
- **Bound Figure Label Resolves to an Embedded Image**: a symbolic label bound to a catalog figure embeds the image via Markdown syntax (`![caption](path){width=...}`) at the label-resolution hook; unbound labels stay text-only; numbering/cross-references unaffected. 3 scenarios.
- **Graceful Degradation on Missing or Corrupt Bound Image**: a missing or corrupt image file degrades to caption-only output with a WARN, never crashes the build; one degraded figure does not affect others. 3 scenarios.
- **Embedded-Image Build Determinism**: the embedded-image build path produces byte-identical output across runs. 1 scenario.

### document-pipeline/spec.md

**MODIFIED**:
- **Ingest Stage and Context-Curation Integration** (requirement name unchanged; only this requirement was touched, no other pipeline requirement was altered): extended to require that the ingest stage also apply the asset-management capability's mechanical role/provenance filter to figure candidates (excluding `guia` example/reference-role images) and copy surviving candidates to the document's stable `assets_dir/figures/` path, so later stages (including assemble-time embedding) can reference them without depending on the ephemeral `inbox/` contents. Added scenario: "Ingest excludes reference-role images and copies survivors deterministically."

## Delivery Ledger

| Slice | PR | Changes | Status |
|-------|----|---------|--------|
| S1 (Domain filter + fields) | #28 | `figure_filter.py` new, `FigureEntry.source_role`/`origin_kind` | MERGED |
| S2 (Ingest wiring) | #29 + hardening (9494fd9) | ingest role filter + stable-path copy + role propagation; orphan-cleanup hardening fix | MERGED |
| S3 (Binding model) | #30 | `figure_binding.py` new, `figure_resolver.py` new, cross-reference embed branch | MERGED |
| S4 (Assembly + determinism) | #31 + hardening (3048f29) | docx/html assembly wiring, determinism coverage; fail-open shape-guard hardening fix | MERGED |

Two post-merge review-driven hardening fixes (9494fd9 orphan-cleanup, 3048f29 fail-open shape guard) are scoped inside their respective slices and carry their own tests.

## Test Evidence

Full suite: `uv run pytest -q` = **1376 passed, 0 failed, 7 skipped** (unchanged — this archive touches specs/docs only, no source code).

`ruff check .`: clean, unchanged.

## Capability Count Verification

No new capabilities created. 3 existing capabilities modified:
1. asset-management (+2 requirements: Mechanical Role Filter, Stable Asset Path; 1 requirement modified in place)
2. document-render (+3 requirements: Bound Figure Label, Graceful Degradation, Build Determinism)
3. document-pipeline (1 requirement modified in place, no requirement added or removed)

Living spec count remains **11 capabilities** (agent-contract, asset-management, context-curation, document-ingest, document-lifecycle, document-pipeline, document-render, document-revise, document-template, template-provisioning, workspace-config) — matching the count documented in the top-level `docs/CLAUDE.md`.

## Verification Status

Verify report (`verify-report.md`, preserved in this archive folder) showed PASS: task completeness confirmed (S0-S4 checked, spec-merge deferred to archive per design), spec conformance confirmed (all requirement/scenario groups mapped to passing tests), no CRITICAL issues, merge tip 23d4290 confirmed.

## Closure Checklist

- [x] Specs merged into `openspec/specs/{asset-management,document-render,document-pipeline}/spec.md`
- [x] Archive report written to `openspec/changes/archive/2026-07-31-smart-figure-embedding/archive-report.md`
- [x] Change folder moved to archive via `git mv` (history preserved — verified via `git status` rename detection)
- [x] Full test suite re-run: 1376 passed / 7 skipped; `ruff check .` clean
