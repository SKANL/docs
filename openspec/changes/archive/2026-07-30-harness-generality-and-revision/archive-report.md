# Archive Report: harness-generality-and-revision

**Change**: harness-generality-and-revision
**Archive date**: 2026-07-30
**Archived to**: `openspec/changes/archive/2026-07-30-harness-generality-and-revision/`
**Mode**: hybrid (openspec + Engram)
**Status**: ARCHIVED AND CLOSED

## TOOLING CAVEAT (read first)

This archive pass was executed by a sub-agent with **no Bash/shell/git tool**
available (only Read/Edit/Write/Glob/Engram/CodeGraph). As a direct result,
three mechanical steps from the archive checklist could **not** be executed
by this agent and remain outstanding — this is flagged explicitly per the
user's warning that a prior archive run silently copied instead of moved:

1. **Original folder not deleted.** `openspec/changes/harness-generality-and-revision/`
   (including its `specs/` subfolder) was fully **copied** to this archive
   path — every file was read and rewritten here — but the original could
   not be removed (no delete/move capability). It still exists on disk and
   must be deleted by a follow-up step with shell access:
   ```
   rm -rf openspec/changes/harness-generality-and-revision
   ```
2. **`uv run pytest -q` not run** by this agent (no shell). The verify-report
   already records a full green run (1300 passed / 0 failed / 7 skipped) on
   the merged branch; re-run to reconfirm on `main` post-archive:
   ```
   uv run pytest -q
   ```
3. **No git commit/push performed** by this agent. The spec merges and
   archive-folder copy are on disk but unstaged/uncommitted. Required
   follow-up:
   ```
   git add -A openspec/
   git rm -r openspec/changes/harness-generality-and-revision
   git commit -m "chore(sdd): archive harness-generality-and-revision (specs merged)"
   git push origin main
   ```

Everything else in this report (spec merges, archive content, this report
itself) is complete and correct as written to disk.

## SDD Artifact Observation IDs (Engram Mirrors)

| Artifact | ID | Topic Key |
|----------|----|-----------|
| Proposal | (mirrored during propose phase) | sdd/harness-generality-and-revision/proposal |
| Spec | (mirrored during spec phase) | sdd/harness-generality-and-revision/spec |
| Design | (mirrored during design phase) | sdd/harness-generality-and-revision/design |
| Tasks | (mirrored during tasks phase) | sdd/harness-generality-and-revision/tasks |
| Apply Progress | 2942 | sdd/harness-generality-and-revision/apply-progress |
| Verify Report | 2945 | sdd/harness-generality-and-revision/verify-report |
| Archive Report | (this document) | sdd/harness-generality-and-revision/archive-report |

## Change Summary

**Objective**: Close three generality gaps blocking `docs` from being a
general-purpose document harness: (1) review/rules hardcoded to
Spanish-APA-estadia; (2) no post-completion semantic revision flow; (3) only
DOCX wired despite a clean renderer seam. Prove generality with a second,
structurally-different template.

**Scope**: 6 bound decisions (A-F) spanning 6 capabilities:
- NEW: `document-revise`, `document-lifecycle`
- MODIFIED: `template-provisioning`, `document-pipeline`, `document-render`,
  `agent-contract`

**Bound Decisions**:
- A. Template-driven review rules (data moves out of `rules.py`/
  `source_role.py` into template config; estadia byte-identical)
- B. `doc revise` semantic-edit loop (diff + scoped re-validation +
  append-only provenance; prose + rippling context-topic edits)
- C. HTML (deterministic) + PDF (best-effort, WARN+skip) renderers via
  `DocumentRendererPort`
- D. Second built-in non-APA template (`technical-report-srs`) + e2e
  acceptance proving A generalizes
- E. Verify-phase clean-room refinement of `AGENTS.md`
- F. Lightweight lifecycle (draft/final) + build version surfaced by
  `doc status`

## Spec Merge Summary

**Newly Created Specs**:
- `openspec/specs/document-revise/spec.md` — 4 requirements (diff output,
  scoped re-validation, change provenance, revise scope boundary)
- `openspec/specs/document-lifecycle/spec.md` — 3 requirements (lifecycle
  state on assemble, monotonic build version, `doc status` surfacing)

**Updated Existing Specs**:
- `openspec/specs/template-provisioning/spec.md` — ADDED 2 requirements
  (template-driven review-rule configuration; second built-in non-APA
  template)
- `openspec/specs/document-pipeline/spec.md` — ADDED 2 requirements (review
  reads rule data from template config; output-format selection); MODIFIED
  the "Reproducibility Boundary Principle" requirement with the PDF
  non-determinism amendment
- `openspec/specs/document-render/spec.md` — ADDED 2 requirements
  (deterministic HTML renderer; best-effort PDF renderer with graceful
  degradation)
- `openspec/specs/agent-contract/spec.md` — ADDED 1 requirement (clean-room
  verification drives AGENTS.md refinement); MODIFIED the "Shipped
  `AGENTS.md`" requirement to cover revise/format/lifecycle documentation

**Pre-existing issue fixed during this merge**: `document-pipeline/spec.md`
contained a **duplicate** "Reproducibility Boundary Principle" requirement
block (one plain, one suffixed "(Item M)") from an earlier archive pass that
didn't dedupe on merge. Both were removed and replaced with a single
requirement carrying the PDF-amended content (docx/HTML byte-determinism,
PDF explicitly non-byte-deterministic, toolchain-absent WARN+skip scenario).

**Total Delta**: 2 new capabilities (7 requirements) + 4 modified
capabilities (7 added requirements + 2 modified requirements, 1 dedup fix).
All requirements map to passing test coverage per `verify-report.md`.

## PR Ledger

**Chained/stacked-to-main delivery**: 7 slices + 1 clean-room follow-up fix,
merged to `main` via PR #22.

| # | Slice | Item | Commit |
|---|-------|------|--------|
| 1 | Template-driven review rules | A | `40f0482` |
| 2 | HTML renderer + `--format` CLI | C-html | `87290f5` |
| 3 | PDF renderer | C-pdf | `26d9995` |
| 4 | `doc revise` loop | B | `6a28f4c` |
| 5 | 2nd built-in template (technical-report-srs) + acceptance | D | `6d4fb9e` |
| 6 | Lifecycle + build version + `doc status` | F | `b3c04ea` |
| 7 | AGENTS.md documentation coverage | E (static content) | `8b76b3f` |
| — | AGENTS.md clean-room fix (12 gaps closed) | E (dynamic clean-room) | `8d58427` |

**Integration**: All 7 slices + the clean-room fix merged to `main` via PR #22.

## Verification Summary

**Test Evidence**:
- Final suite: **1300 passed, 0 failed, 7 skipped**
- `ruff check .`: 8 pre-existing violations, confirmed identical on `main`
  before this change (not introduced)

**Task Completion**:
- All 54 TDD task checkboxes across 7 phases marked `[x]` in `tasks.md`
- No unchecked implementation tasks — Task Completion Gate passed

**Clean-Room Verification (item E) — Result**:
The `agent-contract` spec's own added requirement ("Clean-Room Verification
Drives AGENTS.md Refinement") required a literal dynamic scenario: an agent
given only `AGENTS.md` + raw files, no source/tests access, attempting the
full workflow end-to-end. The original verify pass only ran a static
content-check proxy (WARNING, non-blocking). Per the maintainer's decision,
option (a) was taken: a genuine clean-room sub-agent pass ran pre-archive.

- **Result: the harness IS agent-replicable end-to-end** using only
  `AGENTS.md` and raw input files.
- The clean-room run surfaced **12 contract gaps** — undocumented flags,
  behaviors, or steps an agent following only `AGENTS.md` would have
  stumbled on.
- All 12 gaps were closed by an additive `AGENTS.md` edit, commit `8d58427`.
- The verify-report's WARNING is now resolved and recorded as such in
  `verify-report.md`'s "Post-Verify Update" section in this archive folder.

**Issues**:
- CRITICAL: None (at verify time or after)
- WARNING: 1, resolved during archive (clean-room dynamic pass now run, gaps
  closed)
- SUGGESTION: 1, resolved during verify (`state.yaml` phase-tracking drift
  fixed)
- Verdict: PASS

## Known Code Follow-Ups (not blocking, tracked for a future change)

These are pre-existing or newly-surfaced rough edges observed during
implementation/verification. None are CRITICAL; none block this archive.
Recommend a future SDD change or quick-fix pass if any become user-visible
pain points:

1. **Scaffold text hardcoded APA/Spanish** — despite A's template-driven
   review-RULE config, some scaffold/placeholder text generation still
   assumes APA-style/Spanish conventions rather than reading from the active
   template. Rule DATA is now generalized; scaffold TEXT is not yet.
2. **Output filenames hardcoded `tesina-*`** — generated output filenames
   still carry a `tesina-` prefix regardless of the active template/document
   type, a leftover from the original single-document-type harness.
3. **`mark-final` produces no output/final artifact** — `doc mark-final`
   flips the `lifecycle` field to `"final"` but does not itself trigger or
   produce a distinguished "final" build artifact; a subsequent `assemble`
   is still required and its output looks the same as any draft build.
4. **Git-noise in non-git workspaces** — some workspace/status paths still
   assume or lightly probe for a git repository, producing noise/warnings
   when the harness is used in a plain (non-git) workspace.
5. **`classification-confirm` near-no-op** — the classification-confirmation
   step in the ingest flow does very little beyond echoing back the
   detected classification; it does not yet give an agent/human a
   meaningful override path.

## Affected Files (Summary)

**Code**: `domain/rules.py`, `domain/normative.py`, `domain/source_role.py`,
`application/review.py`, `application/revision.py` (new), `domain/revision.py`
(new), `application/html_render.py` (new), `application/pdf_render.py` (new),
`cli/commands/doc_app.py`, `cli/commands/core_app.py`, `cli/_shared.py`,
`domain/models/document.py`, `domain/document_status.py`,
`application/status.py`, `application/pipeline.py`

**Templates**: `templates/builtin/reporte-estadia-tic.json` (populated
contested-term config), `templates/builtin/technical-report-srs.json` (new,
2nd built-in template)

**Docs**: `AGENTS.md` (revise loop, format selection, lifecycle sections,
plus 12 clean-room-driven gap fixes)

**Specs**: 2 new + 4 updated spec files in `openspec/specs/`

## Archive Integrity

- All source files from the change folder **copied** to this archive folder
  (proposal, design, tasks, verify-report + post-verify update, state.yaml,
  specs/, this archive-report)
- Spec merge completed without loss of existing unrelated content;
  pre-existing duplicate requirement block deduped
- **Original active change folder was NOT deleted** — see TOOLING CAVEAT
  above; this remains an open follow-up for the maintainer/orchestrator
- Engram mirrors: apply-progress (#2942) and verify-report (#2945) confirmed
  present; this archive-report is being persisted to Engram as
  `sdd/harness-generality-and-revision/archive-report`

## Session & Context

- Archive execution: 2026-07-30
- Project: docs
- Artifact store mode: hybrid
- Next recommended phase: none (change is functionally complete; only the
  mechanical cleanup listed in TOOLING CAVEAT remains)

---

**Status**: CLOSED (spec merge + report complete). The SDD cycle for
`harness-generality-and-revision` is functionally done — propose, spec,
design, tasks, apply, verify, and the spec-merge/report portion of archive
are all complete, PR #22 is merged to `main`, and the clean-room WARNING is
resolved. **Outstanding**: delete the original change folder and run
`pytest`/`git add`/`git commit`/`git push` — see TOOLING CAVEAT for exact
commands.
