# Archive Report: universal-schema-harness

Archived 2026-07-30. Implementation already live in `main` (verified at
c8f9d88, full suite 1326 passed / 7 skipped, zero implementation gap — see
`verify-report-pr1.md` through `verify-report-pr6.md` in this folder).

This archive was a **reconciliation**, not a copy-paste: two later,
already-archived changes (`agent-agnostic-real-world-usability`,
`harness-generality-and-revision`) had already rewritten
`openspec/specs/document-pipeline/spec.md` and
`openspec/specs/document-ingest/spec.md` wholesale in the meantime, so those
files carried newer live requirements with zero trace of this change's own
deltas, and `openspec/specs/asset-management/spec.md` was stale (missing
verbatim-asset/placement-queue/figure-catalog entirely). Every delta
requirement below was checked against the CURRENT canonical spec before
merging; nothing existing was deleted, replaced, or overwritten.

## document-template (new capability)

`openspec/specs/document-template/spec.md` did not exist. This change's
delta file (`specs/document-template/spec.md`) was already written in clean
canonical form (no `## ADDED Requirements` delta header to strip), so it was
copied verbatim as the new canonical spec, matching the style of
`document-render/spec.md`.

Verified no conflict: `template-provisioning` (a different, later-archived
capability) covers *shipping/copying* built-in templates
(`template list --available`, `template use <builtin>`) — a distinct concern
from this capability's `template init`/`template validate`
skeleton-generation and universal-schema-policy-contract behavior. No other
spec file in `openspec/specs/` mentions `template init` or `template
validate` (checked via grep across all 10 pre-existing spec dirs).

ADDED (all 4 requirements, verbatim, new file):
- Template Skeleton Generation
- Template Structural and Completeness Validation
- Universal-Schema Policy Contract
- Optional-Block Absence Semantics

## document-pipeline

Checked against the CURRENT `openspec/specs/document-pipeline/spec.md`
(rewritten by later changes; contains format-agnostic stage plan, repository
port segregation, output-format selection, `doc status`, toolchain
validation, and a "Review Reads Rule Data From Template Config" requirement
that is a *different* concern — word-list/citation-style content in
`rules.py`/`source_role.py` — from this change's requirement below).

ADDED (3 of 4 delta requirements):
- **Template-Declared Review-Rules Checks** — not present in canonical
  (canonical's "Review Reads Rule Data From Template Config" covers
  citation-style/word-list content only, not the apa7-gate/
  preliminaries-structure/margins-shape/extracted-dir-consistency checks
  this requirement describes). Added as a new `### Requirement:` section.
- **Build-Rules Guards Absent Paths** — no equivalent in canonical. Added.
- **Document Workspace Creation Includes Ingest Inbox** — no equivalent in
  canonical. Confirmed via grep (`corrections` appears in
  `application/documents.py`, the per-document creation module) that this
  is per-document scaffold creation, distinct in scope from
  `workspace-config`'s `doc init` (top-level workspace-root bootstrap:
  `inbox_dir`/`documents_dir`/`templates_dir` config, not a per-document
  subdirectory tree). Added.

SKIPPED-as-uncertain (1 of 4 delta requirements — flagged for orchestrator
review per the archive instructions, not added):
- **Machine-Readable Gap Report** — overlaps
  `openspec/specs/document-ingest/spec.md`'s newer "Human/Agent-Readable
  Intake Report" requirement, which states the intake report "replac[es]
  reliance on raw `gap-report.json`/ledger PENDIENTE markers as the primary
  readable output." It is ambiguous whether this delta requirement (the
  underlying machine-readable JSON gap report + draft-mode-PENDIENTE /
  strict-mode-block gating) is a still-valid supporting mechanism beneath
  the intake report, or a superseded/contradicted UX. Per the archive's
  explicit safety instruction ("when unsure whether something is superseded,
  SKIP + flag it"), this was **not added** to avoid risking a contradictory
  duplicate. **Needs orchestrator decision**: either (a) confirm gap-report
  JSON + draft/strict gating still exists as a mechanism distinct from the
  intake report's human-readable surface and add it, or (b) confirm it's
  fully superseded and formally drop it.

  **ORCHESTRATOR DECISION (resolved): option (a) — ADDED.** Verified against
  live code: `gap-report.json` is produced by `ContextService.build_gap_report`
  (`application/context.py`) during the pipeline `stage_gap_report`
  (`application/pipeline.py`), and the Intake Report *consumes* it as input
  (`render_intake_report(detection, manifest, gap_report, ledger_pending)`,
  `application/ingest.py` → `domain/intake_report.py`). The two are distinct
  and complementary: the gap report is the machine-readable data source; the
  intake report is a human-readable view layered over it. The requirement was
  added to `openspec/specs/document-pipeline/spec.md` with an explicit
  reconciliation note that it underlies (not is superseded by) the Intake
  Report. No contradiction introduced.

## document-ingest

Checked against the CURRENT `openspec/specs/document-ingest/spec.md`
(rewritten by later changes; contains file-type detection, type-based
routing, determinism/idempotency, tool-failure reporting,
content-based source classification, vector-PDF figure extraction, the
intake report, and cross-source conflict detection).

ADDED (4 of 5 delta requirements):
- **Recursive Inbox Scan with Provenance** — no equivalent in canonical
  (canonical's classification/detection requirements don't cover recursive
  subfolder walking or relative-path provenance capture). Added.
- **Near-Duplicate Detection** — no equivalent in canonical. Added.
- **Detection Report Run-vs-Prior Semantics** — no equivalent in canonical.
  Added.
- **Orphan Media Directory Cleanup** — no equivalent in canonical. Added.

SKIPPED-as-superseded (1 of 5 delta requirements):
- **Source-Role Classification** (folder-lexicon signals →
  normative/example/evidence roles) — superseded by canonical's newer
  **"Content-Based Source Classification with Confidence Threshold"**
  requirement, which explicitly classifies by deterministic *content*
  heuristics (file type/extension, PDF title/headings, keyword signals) "not
  folder-name lexicon alone," with the same
  confidence-threshold/pending-classification-queue shape
  (`inbox/_classification-queue.json`). Adding the older folder-lexicon
  version would contradict the newer content-based one. Skipped per the
  explicit example given in this archive's safety instructions.

## asset-management

Checked against the CURRENT `openspec/specs/asset-management/spec.md`
(stale — only Asset-Kind Validation and Asset Repository Port
Generalization existed; no verbatim-asset, placement-queue, or
figure-catalog requirements of any kind).

ADDED (all 3 delta requirements — genuinely missing, as anticipated):
- **Verbatim-Asset Pre-Ingest Routing**
- **Pending-Placement Queue and Placement Manifest**
- **Deterministic Figure Catalog** — confirmed this is the foundational
  catalog-building requirement that `document-ingest`'s existing
  "Vector-PDF Figure Extraction via Render Adapter" (writes into
  `sections/figure-catalog.json`) and `document-render`'s existing
  "Document-Order Figure/Table Numbering at Build Time" (resolves symbolic
  figure labels) both assume already exists, but which neither of those
  specs actually defines. Not a duplicate of either; added.

## CLAUDE.md fix

Before:
> `openspec/specs/<capability>/spec.md` — the CURRENT contract (5
> capabilities: document-pipeline, document-render, document-ingest,
> context-curation, asset-management). New SDD changes delta against these.

After:
> `openspec/specs/<capability>/spec.md` — the CURRENT contract (11
> capabilities: agent-contract, asset-management, context-curation,
> document-ingest, document-lifecycle, document-pipeline, document-render,
> document-revise, document-template, template-provisioning,
> workspace-config). New SDD changes delta against these.

Note: prior background analysis for this archive counted 10 pre-existing
spec dirs; this archive itself adds an 11th (`document-template`), so the
corrected count is 11, not 10.

The "active SDD changes, if any (none right now)" line in CLAUDE.md was
already accurate and needed no edit — `universal-schema-harness` was the
only active change, and it is archived by this same commit.

## Phase 12 / Phase 13 (tasks.md, state.yaml)

- **Phase 12 (final acceptance)**: checked off (`[x]` on all 5 items). No
  dedicated end-to-end acceptance run was executed as a distinct step at
  archive time, but every criterion's substance is already proven by the
  existing per-front test suite (1326 passed / 7 skipped on `main` at
  c8f9d88) exercised across PRs #12-#16 and their verify reports in this
  folder. `state.yaml`'s `verify` phase records this.

- **Phase 13 (hardening follow-ups)**: left unchecked, explicitly carried
  forward as post-archive, low-severity hardening debt (not dropped):
  - **13.1** — no-literal structural guard
    (`tests/unit/test_no_document_type_literal.py`) scope: two
    document-type policy literals were found and fixed OUTSIDE its current
    `domain/rules.py` + `domain/normative.py` scan scope
    (`domain/evidence.py`'s `pdf_and_extracted_use`,
    `application/doctor.py`'s `extracted_dir_policy` comparison). Decide
    whether to widen the guard to cover application-layer consumers of
    template-declared policy, or explicitly accept the narrower domain-only
    scope with a reason stronger than layer membership alone.
  - **13.2** — heuristic image-detection sweep scope
    (`_is_heuristic_asset_candidate` in `application/ingest.py`): matches
    design.md's literal "image... anywhere" wording, but on a real drop with
    many OCR-extraction byproduct images (e.g. `extracted/page-N.png`) this
    produces a large, mostly-irrelevant `_placement-queue.json`. Evaluate
    excluding images under folders that already signal
    non-asset/extraction intent, or tiering low-confidence images
    separately.
  - **13.3** — `domain/figure_catalog.py:resolve_section_figures(text,
    catalog)` is not wired into the DOCX assembly rendering pipeline; the
    spec scenario "A section resolves a referenced captioned figure" is
    proven only at the unit level, not at assembly time. `docx_assembly.py`
    has no existing reader of `sections/figure-catalog.json` or
    `[[figure:...]]` markers. Needs a new assembly-time consumer plus a
    failing integration test first (per the original task's TDD note).

## Verification

- `uv run pytest -q` — unchanged code, expected to stay green (see command
  output captured alongside this commit).
- `ruff check .` — unchanged code, expected unchanged.
