# Verify Report -- PR6 (Front G: template lifecycle + gap report) -- FINAL FRONT

Change: universal-schema-harness | Branch: feat/usch-g-template-lifecycle
Base: main @ 254ef6c (merge of PR5/Front F, feat/usch-f-assets-figures)
Scope: Phase 11 (11.1-11.11, 11 tasks) -- the final implementation front.
Phase 12 (final acceptance) and Phase 13 (hardening follow-ups) remain
correctly disclosed as open, cross-front closeout work, not this front's
scope.
Reviewer: sdd-verify (fresh-context adversarial review, sixth and final
target in this change)

## Executive Summary

Front G's template lifecycle half (template init/validate) is genuinely
solid: non-vacuous, real-CLI-driven tests confirm validate_template
rejects real invalidity and accepts both real fixtures, and the
init-then-validate round trip is proven end to end, exactly following the
"PR5 CRITICAL lesson" the apply-progress explicitly cites. But this review
found the CRITICAL finding the coordinator's own priority probe #1
predicted and asked to be probed hard: build_gap_report's section-content
gap detection is PROVABLY INERT for the single most common real-world
case -- a section that is still just the harness's own freshly-generated
render_contract_scaffold() output, never actually written by a human or
AI. The scaffold's own boilerplate text ("PENDIENTE: documentar {item} con
evidencia...") embeds each required_content item's own words verbatim,
which trivially satisfies rules.requirement_present()'s substring check --
so a document consisting entirely of unedited scaffolds reports ZERO
section gaps, and strict mode's entire gap-blocking mechanism (the
feature's whole reason to exist) never fires for this case. Independently,
empirically reproduced end to end against the real render_contract_
scaffold + ContextService.build_gap_report. Context-field gaps (the
OTHER half of the gap report) are unaffected -- confirmed via a separate
code path with no shared mechanism. Verdict: needs-fixes.

## CRITICAL-1 -- Section-content gap detection is inert against the harness's own auto-generated scaffold text, defeating strict mode's core purpose

- Where: src/docs/application/context.py, ContextService.build_gap_report
  (section_gaps loop, calling rules.requirement_present); the root cause
  lives in src/docs/domain/section_rendering.py, render_contract_scaffold,
  which emits one line per required_content item: "- PENDIENTE: documentar
  {item} con evidencia del ledger, contexto o fuentes."
- requirement_present(requirement, plain, detect): when no explicit
  `detect` override exists for a requirement, it falls back to checking
  whether the requirement string OR any of its own words (>=4 chars)
  appears as a SUBSTRING anywhere in the section's plain text. The
  scaffold's PENDIENTE line for requirement "objetivo del proyecto"
  literally contains the text "documentar objetivo del proyecto con
  evidencia..." -- so the requirement's own words are always present in
  the very sentence that is supposed to be marking it as NOT yet done.
- Independently, empirically reproduced end to end, twice: (1) called
  render_contract_scaffold directly with a genuine SectionContract
  (required_content=["objetivo del proyecto", "justificacion", "problema"])
  and confirmed requirement_present() returns True for all three against
  the RAW, completely unedited scaffold text; (2) called the REAL
  ContextService.build_gap_report with that same real scaffold output as
  the section's body -- section_gaps came back as an EMPTY LIST. A
  document where literally none of the three required items have been
  documented reports zero section gaps.
- This is the exact "inert feature, PR5's lesson" pattern: the mechanism
  exists, is wired, is called by the real pipeline stage, and produces a
  well-formed artifact -- but silently fails to detect the one condition
  it exists to catch, for the single most common real-world state a
  section is in right after generation (freshly scaffolded, not yet
  written).
- Compounding severity: stage_gap_report's strict-mode blocking
  (src/docs/application/pipeline.py) only fires "if gap_count and strict".
  Since section_gaps is 0 for scaffold-only sections, a document consisting
  ENTIRELY of unwritten, auto-generated sections would pass strict mode's
  gap gate with zero blocking -- the exact scenario "Strict mode blocks on
  gaps" (spec: document-pipeline) exists to prevent.
- Existing test coverage does not catch this because it never exercises
  the real scaffold text: the unit test
  (test_missing_section_required_content_appears_as_a_section_gap) uses a
  hand-typed section body ("Este texto solo menciona el objetivo del
  proyecto.") that happens to be short of "alcance" -- a plausible-looking
  but synthetic input, never the actual render_contract_scaffold() output.
  All three real-pipeline integration tests in test_pipeline_strict_gap.py
  never create a section file for "introduccion" at all (section_exists()
  returns False, so it is skipped from section_bodies entirely) and never
  assert anything about report["section_gaps"] -- they only test the
  context-field-gap path. The new documento-generico end-to-end acceptance
  test (test_documento_generico_full_prep_pipeline_passes_with_zero_errors)
  runs the real build-sections stage (which would genuinely scaffold real
  sections) but asserts only report["context_gaps"], never
  report["section_gaps"], so this exact inertness never surfaces as a
  test failure there either, even though it is almost certainly reproducible
  on that same fixture.
- Context-field gaps (the OTHER half of build_gap_report, via
  ContextService.status/missing_fields) are NOT affected -- confirmed by
  code inspection: that path never touches section body text or
  requirement_present at all, it is a structurally separate mechanism
  checking whether a context topic's stored data has its required fields
  populated. The coordinator's own framing ("probably fine") is confirmed
  correct.
- Recommendation: requirement_present's substring heuristic is fine for
  POST-HOC review (text a human/AI has already worked on, where the
  harness's own PENDIENTE scaffolding has presumably been replaced), but
  is the wrong tool reused for PRE-EMPTIVE gap detection against
  potentially-still-scaffolded text. Options: (a) have build_gap_report
  detect and treat scaffold-only sections as wholesale missing (e.g. a
  sentinel marker or a check for the scaffold's own "Borrador inicial
  generado por el arnés" banner line, treating its presence as "nothing
  real written yet" regardless of what requirement_present says), or (b)
  strip/ignore the "PENDIENTE: documentar {item}..." lines themselves
  before running requirement_present against the remaining text, or (c) a
  dedicated, stricter presence check for gap-report purposes that does not
  reuse review's substring heuristic. Whichever fix is chosen, add a test
  that drives real render_contract_scaffold() output through the real
  build_gap_report(), the same non-vacuous pattern already used correctly
  elsewhere in this front (test_template_cli.py, test_pipeline_strict_gap.py).

## 2. Priority Probe: template validate Non-Vacuous (checked against PR4's lesson)

Confirmed genuinely non-vacuous, re-ran the full test file directly (12
tests, all pass): both real fixtures (documento-generico.json,
reporte-estadia-tic.json) pass with zero issues, AND a battery of
genuinely-broken constructions are each correctly rejected with the
specific field named -- a missing required top-level block, an orphan
section with no matching contract, a duplicate context_schema topic id, a
body_pagination_start referencing a nonexistent section, a non-numeric
margin value, a "TODO" sentinel, and a "null" sentinel. Unknown extension
keys and "$comment" siblings are correctly tolerated, never flagged. This
is not an accept-everything validator -- it genuinely discriminates.

## 3. Priority Probe: template init Skeleton

Independently re-ran test_init_output_is_byte_identical_across_two_runs
(passes) and the full init-then-validate round trip via the REAL Typer
CLI (CliRunner, not calling the domain functions directly): a fresh
`template init` output correctly fails `template validate` (every TODO
named as incomplete), and after filling every TODO field by hand, the
SAME file passes `template validate` cleanly. The skeleton is neither
self-contradictory (accidentally already "valid") nor unfixable (filling
the documented TODOs genuinely produces a passing template) -- confirmed
end to end via the real CLI process, matching this front's own explicitly
stated "PR5 CRITICAL lesson" discipline.

## 4. Priority Probe: Draft/Strict Gap Wiring

Re-ran test_pipeline_strict_gap.py's three tests directly against the
REAL PipelineService.run_pipeline("prep", ...) sequence (not a fake stage
callable, confirmed via direct read of the test file): draft mode
proceeds past gap-report to pack-context while the gap report on disk
genuinely lists the detected (context-field) gap; strict mode's
summary["passed"] goes False and pack-context never runs when that same
field is missing; filling the field makes strict mode proceed too. This
wiring is genuinely real and correctly gates on gap_count -- the
mechanism itself is sound; CRITICAL-1 is specifically that gap_count
under-counts for scaffold-only sections, not that the draft/strict gate
around gap_count is broken.

## 5. Priority Probe: Task 11.7 Layering Judgment

Confirmed ContextService.__init__ is UNCHANGED (still exactly
context_repo/document_repo/context_markdown, 3 params) -- the resolution
chosen (writer as an optional METHOD parameter on build_gap_report,
defaulting to the same _InlineJsonWriter fallback IngestService already
uses, with the pipeline stage passing self.ingest_service.writer, the
REAL atomic FilesystemIngestArtifactWriter instance already built once in
Deps.__init__) genuinely honors design.md Decision 9's "no new
ContextService dependency" while still getting a real atomic write in
production, with zero new composition-root wiring. Confirmed hexagonal
direction is preserved throughout this front: domain/template_
validation.py and domain/template_skeleton.py import only stdlib +
pydantic + other domain modules (docs.domain.models.template,
docs.domain.review, docs.domain.rules) -- no application or
infrastructure import anywhere in either file.

## Independent Re-run Evidence (this pass)

- Full suite run twice independently: 1084 passed, 0 failed, 7 skipped
  both times, byte-identical counts. Matches the claimed count exactly.
- ruff check: 15 errors on this branch. Compared against CURRENT main
  (post-PR5-merge, commit 254ef6c tree) via a disposable git worktree
  (added and removed cleanly, never touching the live working tree) --
  also 15 errors, identical file:line violation set. 0 net new.
- mypy on all 7 touched files (application/context.py,
  application/pipeline.py, domain/pipeline.py, domain/template_skeleton.py,
  domain/template_validation.py, cli/commands/template_app.py,
  cli/_shared.py): no issues attributable to these files; remaining
  errors are the same pre-existing transitive third-party-stub gaps
  observed throughout this entire change.
- Independently, empirically reproduced (not just read from the diff or
  trusted from existing tests): the gap-report inertness end to end
  against real render_contract_scaffold output (CRITICAL-1); the
  template-validation battery of real-fixture-accept plus
  genuine-invalidity-reject cases; the full init/validate CLI round trip
  including determinism; the real draft/strict pipeline gate.
- Slice discipline: confirmed no leftover leakage -- this is genuinely
  the last front, Phase 12/13 are explicitly and correctly disclosed as
  open cross-front closeout work, not silently completed or silently
  dropped from this front's own scope.
- No checkout-main-onto-live-tree mistake was made during this review; all
  main-baseline comparisons used a disposable git worktree add/remove.

## Issues Summary

| Severity | Count | Items |
|----------|-------|-------|
| CRITICAL | 1 | section-content gap detection is inert against the harness's own auto-generated scaffold text; strict mode's core blocking purpose is defeated for the most common real-world case |
| WARNING | 0 | none |
| SUGGESTION | 0 | none |

## Verdict

needs-fixes -- CRITICAL-1 is severe specifically because this is the
final front and the stated design purpose of strict mode ("blocks on
gaps") is silently defeated for section content, the more consequential
half of the gap report (context-field gaps work correctly). The fix is
narrowly scoped (requirement_present's reuse for pre-emptive gap
detection, not a broad quality problem across this front) and the rest of
Front G -- template init/validate, the CLI round trip, draft/strict
wiring, layering discipline -- is genuinely solid and independently
verified throughout this pass, following the same non-vacuous-testing
discipline this front's own apply-progress explicitly and correctly
cites as a carried lesson from PR5. Recommend fixing CRITICAL-1 (and
adding a real-scaffold-driven regression test for it) before this final
front, and therefore the whole change, is considered feature-complete.
