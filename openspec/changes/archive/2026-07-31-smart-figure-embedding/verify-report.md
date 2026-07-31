# Verify Report: smart-figure-embedding

Verified against main tip 23d4290 (all 4 slices S1-S4 merged, PRs #28-#31).
Artifact store: hybrid. Engram mirror: `sdd/smart-figure-embedding/verify-report` (id 2987).
Materialized on disk by the orchestrator (the sdd-verify sub-agent had no Write tool this session).

## Status: PASS

0 CRITICAL, 0 WARNING, 0 SUGGESTION (beyond two pre-existing `ponytail:` markers).

## Test evidence
- Full suite: `uv run pytest -q` → **1376 passed, 0 failed, 7 skipped**.
- Targeted (10 smart-figure-embedding test files, verbose) → **115 passed, 0 failed**.

## Spec conformance (11 requirement/scenario groups → real merged code + passing test)
- **asset-management**: Deterministic Figure Catalog (MODIFIED — `FigureEntry.source_role`/`origin_kind`), Mechanical Role Filter (ADDED — `domain/figure_filter.should_catalog_figure`), Stable Asset Path (ADDED — `ingest.py:_copy_standalone_figure` + atomic `_copy_asset`).
- **document-render**: Bound Figure Label (ADDED — `figure_binding` + `cross_reference.bound_figures` + `figure_resolver.build_bound_figures_resolver`), Graceful Degradation (ADDED — resolver WARN+exclude, shape-hardening), Embedded-Image Determinism (ADDED — byte-identical rebuild test).
- **document-pipeline**: Ingest Stage (MODIFIED — role filter + stable-path copy wired into `_build_figure_catalog`).

## Tasks completeness
0.1-0.2, 1.1-1.5, 2.1-2.9, 3.1-3.7, 4.1-4.10 all ticked and spot-checked against real on-disk code. Task 5.1 (spec-delta merge) genuinely NOT yet applied to `openspec/specs/` (confirmed by grep) — correctly deferred to the archive phase.

## Non-regression / determinism
Default no-bindings path byte-identical to pre-change (`test_bound_figures_omitted_reproduces_todays_output_byte_for_byte`); estadia/reporte-estadia-tic characterization (6 cases) green.

## Deviation check (ADR-6)
`test_build_degrades_gracefully_for_corrupt_but_present_bound_image` writes garbage bytes to a present file + a null-dims catalog row (the real ingest-time-parse-failure signal). The "corrupt-but-present → null-dims" reconciliation is sound, not a scenario left unimplemented.

## Post-merge hardening (in-scope, from review lenses)
- Orphan cleanup for sub-threshold PDF renders dropped by the filter (S2 review).
- Fail-open on shape-malformed bindings/catalog JSON — never crash the build (S4 review, CRITICAL).

## Next: sdd-archive (merge the 3 delta specs into openspec/specs/, move change to archive/).
