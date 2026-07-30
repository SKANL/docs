# Archive Report: agent-agnostic-real-world-usability

**Change**: agent-agnostic-real-world-usability
**Archive date**: 2026-07-30
**Archived to**: `openspec/changes/archive/2026-07-30-agent-agnostic-real-world-usability/`
**Mode**: hybrid (openspec + Engram)
**Status**: ARCHIVED AND CLOSED

## SDD Artifact Observation IDs (Engram Mirrors)

For full traceability, all artifacts are persisted in Engram with these IDs:

| Artifact | ID | Topic Key |
|----------|----|-----------| 
| Proposal | 2921 | sdd/agent-agnostic-real-world-usability/proposal |
| Spec | 2922 | sdd/agent-agnostic-real-world-usability/spec |
| Design | 2924 | sdd/agent-agnostic-real-world-usability/design |
| Tasks | 2925 | sdd/agent-agnostic-real-world-usability/tasks |
| Verify Report | 2931 | sdd/agent-agnostic-real-world-usability/verify-report |
| Archive Report | (this document) | sdd/agent-agnostic-real-world-usability/archive-report |

## Change Summary

**Objective**: Make the `docs` harness usable end-to-end by any code agent (Claude Code, Codex, OpenCode) over plain CLI + files without manual glue, and robust to messy real-world input.

**Scope**: 13 resolved items (A–M) spanning 6 capabilities:
- NEW: workspace-config, agent-contract, template-provisioning
- MODIFIED: document-ingest, document-pipeline, document-render

**Bound Decisions**:
1. Bring-your-own-agent mechanical harness with documented contract (NO embedded LLM/API keys)
2. Content-based classification + graceful fail-open degradation (not hard-fail)
3. Section `.md` prose as durable truth; `.docx` as deterministic build function

## Spec Merge Summary

**Newly Created Specs**:
- `openspec/specs/workspace-config/spec.md` (persisted workspace config + `doc init` bootstrap)
- `openspec/specs/agent-contract/spec.md` (shipped `AGENTS.md` + `docs guide` CLI command)
- `openspec/specs/template-provisioning/spec.md` (built-in templates as package data)

**Updated Existing Specs**:
- `openspec/specs/document-ingest/spec.md` — ADDED 4 requirements (content classification, vector-PDF extraction, intake report, cross-source conflict)
- `openspec/specs/document-pipeline/spec.md` — ADDED 4 requirements (fail-open doctor, doc status, toolchain validation, reproducibility boundary)
- `openspec/specs/document-render/spec.md` — ADDED 2 requirements (figure/table numbering, evidence-aware review precision)

**Total Delta**: 6 new capabilities + 10 new requirements across 3 existing capabilities. All requirements map to passing test coverage.

## PR Ledger

**Chained/stacked-to-main delivery**: 10 PRs, ~2000 total authored lines (~140-250 per slice)

| # | Slice | Items | Status | Commits |
|---|-------|-------|--------|---------|
| 1 | Fail-open doctor + toolchain + ContentProbePort | E, L | Merged | e1bf73b |
| 2 | Workspace config + `doc init` | A | Merged | 6e02c38 |
| 3 | Built-in template provisioning | C | Merged | 7812776 |
| 4 | Content-probe extension + classification | D | Merged | bdee706 |
| 5 | Wire PDF render adapter into ingest | F | Merged | 676ae15 |
| 6 | Figure/table numbering + cross-ref | H | Merged | 00cb504 |
| 7 | Evidence-aware review precision | J | Merged | 36acb77 |
| 8 | Cross-source conflict + intake/gap report | G, K | Merged | 6b72245 |
| 9 | `doc status` | I | Merged | d1f780c |
| 10 | Agent contract (`AGENTS.md`/`docs guide`) + reproducibility principle | B, M | Merged | 42f41bf |

**Integration**: Merged to `main` via PR #19 + PR #20. Hotfix commit 23ad2f8 ("restore CURATED_INDEX_FILENAME re-export used by pipeline") landed post-merge, fixed a regression from prior cleanup (outside the 10-slice chain, full suite green with it).

## Verification Summary

**Test Evidence**: 
- Suite: 1227 passed, 0 failed, 7 skipped (all phases complete)
- Ruff: clean
- CLI smoke checks: all commands present and functional

**Task Completion**: 
- All 63 TDD task pairs across 10 phases marked [x]
- No unchecked implementation tasks
- State.yaml apply-phase note confirms test results

**Compliance Matrix (A-M)**:
- All 13 items satisfied with code + passing test evidence
- All spec scenarios have covering tests
- Design architectural seams match actual landing points

**Issues**:
- CRITICAL: None
- WARNING: None
- Verdict: PASS

## Next Steps / Follow-ups

**Immediate** (deferred, not blocking archive):
1. opendataloader image_output gate refinement (improved confidence thresholding for raster extraction)
2. pending-marker adjective refinement (further tighten the word-boundary rule on PENDIENTE variants)

These are suggestion-level enhancements noted during verify, not issues with the current implementation. Archive is complete and ready for production.

## Affected Files (Summary)

**Code & CLI**: 
- `cli/_shared.py`, `cli/commands/doc_app.py`, `cli/commands/template_app.py`, `cli/commands/core_app.py`
- `domain/workspace_config.py`, `domain/cross_reference.py`, `domain/source_conflict.py`, `domain/intake_report.py`
- `domain/ports/content_probe_port.py`, `infrastructure/ingest/content_probe_adapter.py`
- `application/doctor.py`, `application/ingest.py`, `application/docx_assembly.py`, `application/status.py`
- `domain/rules.py`, `domain/source_role.py`, `domain/doctor.py`
- `src/docs/templates/builtin/reporte-estadia-tic.json`
- `AGENTS.md` (new root file, force-included as package data)
- `pyproject.toml` (force-include entry, hatch config)

**Tests**: 60+ new/modified test files across unit, integration, and e2e suites

**Specs**: 6 new + 3 updated spec files in `openspec/specs/`

## Archive Integrity

- All source files from change folder copied to archive (proposal, design, tasks, verify-report, state.yaml)
- All artifacts persisted to Engram with observation IDs above
- Spec merge completed without loss or modification of existing unrelated content
- Change folder moved to archive with date prefix
- No active-state files remain in `openspec/changes/agent-agnostic-real-world-usability/`

## Session & Context

- Archive execution: 2026-07-30
- Project: docs
- Artifact store mode: hybrid
- Engram mirror: Full artifact chain with all observation IDs recorded
- Next recommended phase: none (change is complete and closed)

---

**Status**: CLOSED. The SDD cycle for `agent-agnostic-real-world-usability` is complete. All phases (propose, spec, design, tasks, apply, verify, archive) are done. The change is merged to main, specs are synced, and the change folder is archived.
