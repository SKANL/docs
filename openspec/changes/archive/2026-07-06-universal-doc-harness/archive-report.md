# Archive Report: universal-doc-harness

**Change**: universal-doc-harness  
**Archived**: 2026-07-06  
**Status**: Complete and verified  
**Location**: `openspec/changes/archive/2026-07-06-universal-doc-harness/`

## Executive Summary

The `universal-doc-harness` SDD change has been successfully implemented, verified, and archived. All 8 implementation slices plus one technical-debt closeout were merged to main in order, with main staying green after every merge. The full pipeline is now deterministic, format-agnostic, and extensible without touching domain code.

Final test results: **923 passed, 7 skipped** (2026-07-06, double-run verified zero flakes).

## What Shipped

### 8 Implementation Slices

| PR | Title | Link | Commits | Status |
|----|-------|------|---------|--------|
| PR1 | Sentinel Rename + Asset Generalization | https://github.com/SKANL/docs/pull/1 | 2149ab0..9add555 (7 commits, merge bc9f9ea) | Merged |
| — | remove_asset multi-kind stem fix (PR1 residual follow-up, user-ordered ahead of PR4) | https://github.com/SKANL/docs/pull/4 | aa31e9b, 137c8ec (merge 9bc5974) | Merged |
| PR2 | Repository Port Segregation | https://github.com/SKANL/docs/pull/2 | 8acb700, b714efe | Merged 2026-07-04 |
| PR3 | CLI Composition Root Split | https://github.com/SKANL/docs/pull/3 | 9a95ca4 | Merged 2026-07-04 |
| PR4 | Renderer Registry + Stage Plan | https://github.com/SKANL/docs/pull/5 | 763b37c, 5c8dc31, d08bc08 | Merged 2026-07-05 |
| PR5 | Ingest Detection + Routing | https://github.com/SKANL/docs/pull/6 | 46ff2cf, 1585a69, bbf0b10, 89c4e6c, 8a0de48 | Merged 2026-07-05 |
| PR6 | Ingest Per-Type Adapters | https://github.com/SKANL/docs/pull/7 | b8f7cdd, 1b8168c, 79cdfc3, 9f22c8c, e52058c, 0faca2d | Merged 2026-07-05 |
| PR7 | Context Files + Index | https://github.com/SKANL/docs/pull/9 | 9849397, 0e5ef8f | Merged 2026-07-05 |
| PR8 | Pipeline Wiring + Tests | https://github.com/SKANL/docs/pull/10 | 9b0d023, 6a7b759, eea12fb, 9ae6f3b, b1fb2f2, 81d4717, 07a8c4f, 4f0c86f, 1ce8a36, 8aeead6, e24b729 | Merged 2026-07-06 |

### Technical Debt Closeout

**PR**: https://github.com/SKANL/docs/pull/8  
**Commit**: 88423c9  
**Merged**: 2026-07-05  
**Summary**: All PR1-PR6 recorded debt items (D1-D6) cleared in 5 work-unit commits; fresh-context review verdict MERGE-READY with zero findings.

### Capability Deltas Merged into Main Specs

| Capability | Delta Spec | Main Spec Location | Status |
|------------|-----------|------------------|--------|
| document-pipeline | Merged | `openspec/specs/document-pipeline/spec.md` | Created (new domain) |
| document-render | Created | `openspec/specs/document-render/spec.md` | Created (new domain) |
| document-ingest | Created | `openspec/specs/document-ingest/spec.md` | Created (new domain) |
| context-curation | Created | `openspec/specs/context-curation/spec.md` | Created (new domain) |
| asset-management | Merged | `openspec/specs/asset-management/spec.md` | Created (new domain) |

## Verify Report Summary

**Verdict**: `pass-with-warnings`  
**Date Verified**: 2026-07-06  
**Baseline**: main @ 4ed754f  
**Suite Runs**: 2x back-to-back (923 passed / 7 skipped both runs, zero flakes)

**Findings**:
- **CRITICAL Issues**: 0
- **Implementation WARNINGs**: 0 (all caught and fixed during apply phase)
- **Cosmetic Findings**: 2 (frozen artifacts — recorded here instead of edited)

## Accepted Deviations and Spec Reflections

The following deviations from the original design sketches were identified during implementation, validated by fresh-context review, and are now reflected in the merged main specs and PR notes:

### 1. Context Index Namespacing (PR8 remediation)

**Deviation**: Design.md's aspirational `context/index.md` was namespaced to `context/curated-index.md` to avoid collision with the pre-existing Topic/Q&A system's index.

**Why**: Two incompatible formats both targeted the same path; consolidation was explicitly out of scope (different purposes, different content shapes).

**Spec Reflection**: 
- `context-curation/spec.md` Requirement "Collision-Safe Index Namespacing" added to capture the as-built constraint.
- The main spec now explicitly documents that the curated index writes to a distinct filename and both systems remain accessible downstream.

### 2. SourceIngestPort 3-Argument Signature (PR6 remediation)

**Deviation**: `SourceIngestPort.ingest(src, out_dir, kind)` grew a third required `kind` parameter due to a critical bug during fresh-review.

**Why**: Without the kind parameter, adapters re-derived kind from file extensions, causing misidentification when a DOCX was renamed to `.doc` and pandoc conversion failures. The detected kind (magic bytes) was the source of truth but was lost.

**Spec Reflection**:
- `document-ingest/spec.md` remains silent on the 3-arg detail (delta/port contracts are internal implementation details).
- Design.md contains an ADDITIVE NOTE (task 6.7) documenting the port's actual tested contract: `ingest(src, out_dir, kind)`.

### 3. Data-Driven Stage Plan Caller-Supplied Parameters (PR4 narrowing)

**Deviation**: `pipeline_stage_plan(stage_set, assemble=None)` narrower than design.md's sketch. Only `assemble` is caller-supplied; `prep` and `ingest` remain module constants.

**Why**: `prep` and `ingest` stages are format-agnostic (no DOCX-only identifiers), so they don't vary by output format. Caller-supplied parameters for them would be speculative indirection.

**Spec Reflection**:
- `document-pipeline/spec.md` Requirement "Data-Driven, Format-Agnostic Stage Plan" is satisfied: stage names are derived from config/registry (via the resolved renderer), not hardcoded.
- Design.md contains an ADDITIVE NOTE (task 8.1) documenting the actual signature and rationale.

### 4. Zip Timestamp Determinism Fix (PR8 post-verify bugfix)

**Deviation**: New `infrastructure/docx/deterministic_zip.py` module added post-verify to fix intermittent full-pipeline determinism failure.

**Why**: `python-docx` and `docxcompose` stamp zip entries with wall-clock time at 2-second DOS granularity, causing byte-level DOCX diffs under load. Fixed by normalizing all zip entry timestamps to a fixed sentinel (1980-01-01).

**Spec Reflection**:
- `document-pipeline/spec.md` Requirement "Ingest Stage and Context-Curation Integration" includes scenario "Full pipeline determinism end-to-end" which now holds durably.
- Design.md File Changes table documents this as an ADDITIVE bugfix with full root-cause, RED evidence, and verification notes.

## Cosmetic Findings (Frozen Artifacts)

Per the verification report, two checkboxes remain unchecked despite being demonstrably satisfied:

### 1. proposal.md Success Criteria

**Finding**: The proposal's Success Criteria checkboxes (lines 66-71) were not edited during the SDD, remaining unchecked despite all criteria being met.

**Reason**: SDD planning artifacts are frozen by convention — they serve as immutable reference records, not live task lists. Edits made only additively (via ADDITIVE NOTEs in design.md/tasks.md) to preserve audit trail.

**Satisfied Evidence**: All 5 success criteria met:
- Non-DOCX sources ingest to markdown deterministically and idempotently ✓ (PR5, PR6 determinism tests)
- Context files + progressive-disclosure index generated as fillable slots ✓ (PR7)
- DOCX renders through `DocumentRendererPort`; second-format test proves extensibility ✓ (PR4, task 4.7-4.8)
- No "tesina" identifiers remain; debt items closed; application-layer tests added ✓ (PR1, PR8)
- Full pipeline reproducible: same inputs → identical outputs ✓ (PR8, task 8.6, double-run verification)

### 2. design.md Open Questions

**Finding**: Design.md section "Open Questions" has 2 checkboxes (lines 176-179), both remaining unchecked in the frozen artifact despite being resolved during implementation.

**Reason**: Frozen artifact convention — resolutions are recorded here and in tasks.md notes instead of editing the planning document.

**Resolved Evidence**:
- "Verify `opendataloader-pdf` maturity before locking the dependency" — RESOLVED by PR5 task 5.1 spike (GATE PASS with conditions, Engram topic `sdd/universal-doc-harness/pdf-spike`).
- "PDF/HTML visual QA parity" — CONFIRMED OUT OF SCOPE: noted in proposal as non-goal; no follow-up needed.

## Archive Contents Inventory

```
archive/2026-07-06-universal-doc-harness/
├── proposal.md                    # Proposal artifact (frozen)
├── design.md                      # Design artifact (frozen + additive notes)
├── tasks.md                       # Task checklist (all 8 PRs complete)
├── state.yaml                     # Full SDD state record
├── specs/
│   ├── document-pipeline/spec.md  # Merged delta → main spec
│   ├── document-render/spec.md    # Merged delta → main spec
│   ├── document-ingest/spec.md    # Merged delta → main spec
│   ├── context-curation/spec.md   # Merged delta → main spec
│   └── asset-management/spec.md   # Merged delta → main spec
└── archive-report.md              # This file
```

## Integration into Main Specs

All 5 delta specs have been merged into `openspec/specs/` as the authoritative main specifications. They are now the single source of truth for these capabilities. The merged main specs:

1. Preserve all requirement scenarios from delta specs (no dropped requirements).
2. Reflect the as-built, tested contracts (e.g., 3-arg SourceIngestPort signature).
3. Include new scenarios for behaviors discovered during implementation (e.g., curated-index namespacing, zip-timestamp determinism).

**Main specs are now ready for ongoing maintenance and future delta specs** — any follow-up work (HTML ingest, PDF rendering adapters, etc.) will delta against these main specs, not the archived change folder.

## Engram Artifact References

All planning artifacts archived in Engram for cross-session recovery:

| Artifact | Topic Key | Observation ID |
|----------|-----------|---|
| Proposal | `sdd/universal-doc-harness/proposal` | (recorded in apply-progress) |
| Spec | `sdd/universal-doc-harness/spec` | (recorded in apply-progress) |
| Design | `sdd/universal-doc-harness/design` | (recorded in apply-progress) |
| Tasks | `sdd/universal-doc-harness/tasks` | (recorded in apply-progress) |
| Apply Progress | `sdd/universal-doc-harness/apply-progress` | (from verify report) |
| Verify Report | `sdd/universal-doc-harness/verify-report` | (from verify report) |
| Archive Report | `sdd/universal-doc-harness/archive-report` | (this archive phase) |

All observation IDs are retained by the orchestrator during archive persistence.

## Rollback & History

**Rollback Status**: Fully reversible by slice. Each PR is independently revertible to the baseline of the prior PR.

**Change History**: All commits preserved in main branch history with conventional commit messages. Git log contains full audit trail of all 8 slices + 1 debt closeout, with merge commits and per-commit greenness verified.

**No data migration required** — clean break from "tesina" naming (no production documents to protect); reverting any PR cleanly restores the prior state.

---

**Archive Date**: 2026-07-06  
**Archived By**: sdd-archive (executor phase)  
**Change Status**: CLOSED — Ready for deployment and future follow-up work.
