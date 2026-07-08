# Verify Report -- PR2 (Front B: orphan _media/ cleanup + doctor.py de-hardcode)

Change: universal-schema-harness | Branch: feat/usch-b-bootstrap-media
Base: main @ d7ad6b5 (merge of PR1, feat/usch-a-policy-dehardcode)
Scope: Phase 6 only (4 tasks) plus NEW-SUGGESTION-1 (doctor.py sibling
literal, a PR1 verify follow-up folded in per orchestrator instruction).
Fronts C-G (Phases 7-12) intentionally not implemented -- not evaluated
here except for slice-discipline leakage.
Reviewer: sdd-verify (fresh-context adversarial review, second target in
this change)

## Executive Summary

PR2 is functionally correct on its core claims (961/961 tests pass twice,
ruff/mypy baselines unchanged versus current main) but carries real gaps
under adversarial pressure: 1 WARNING for a genuine data-loss edge case in
media cleanup (a foreign file placed inside a shape-matching orphan
directory is destroyed along with it, with no distinct reporting), 1
WARNING for a missing real-fixture-driven test on the doctor.py fix (the
same category of gap that caused PR1's CRITICAL-1), 1 WARNING for an
undisclosed field-naming deviation from the literal task/design wording,
and 1 WARNING on the no-literal guard's scope-disposition rationale being
weaker than presented. 2 SUGGESTIONs (per-item exception handling in the
cleanup loop; CLI-facing visibility of media cleanup activity). No
CRITICAL findings. Verdict: needs-fixes (all findings are narrow-scope and
independently fixable; none block on a fundamental design flaw).

## 1. Media Cleanup Correctness (adversarial cases)

Reproduced each case directly against IngestService (not just reading the
diff):

- Paired .md EXISTS -- CORRECT: verified via the existing
  test_content_addressed_media_dir_with_paired_md_is_preserved test and by
  reading the code path (paired_md.exists() short-circuits before rmtree).
  Not deleted.
- Dir matches *_media suffix but not the exact <stem>-<kind>-<sha8> shape
  (e.g. manually_added_media) -- CORRECT: refused, left in place, reported
  under refused. Verified via the existing dedicated test and independently
  reproduced.
- Case sensitivity of the sha8 hex -- CORRECT (independently reproduced): a
  dir named with UPPERCASE hex (readme-md-A1B2C3D4_media) is refused, not
  deleted, because the regex requires [0-9a-f]{8} lowercase only. A 7-char
  (one-short) hash variant is also correctly refused. Both fail toward
  safety (refusal), not deletion.
- Nested weirdness -- NOT APPLICABLE / safe by construction: the scan uses
  ingested_dir.iterdir() (one level only, not recursive), so a _media dir
  nested inside another _media dir is never descended into or discovered as
  a top-level candidate. No recursion risk.
- Symlinks (independently reproduced on this Windows system): a directory
  entry that is actually a symlink to a real directory, named to match the
  content-addressed shape with no paired .md, causes shutil.rmtree to RAISE
  ("Cannot call rmtree on a symbolic link") rather than delete through the
  link -- a safe failure mode for the target directory's contents, but see
  SUGGESTION-1 below: this exception is NOT caught per-item, so it would
  abort the entire ingest_inbox call rather than being reported as a
  refused/errored item and letting the scan continue.
- A FOREIGN FILE placed INSIDE an otherwise-legitimate orphan directory --
  see WARNING-1 below. This is a genuine gap.

### WARNING-1 -- A foreign file placed inside a shape-matching, paired-.md-absent _media/ dir is silently destroyed with the directory

- Where: src/docs/application/ingest.py, _clean_orphan_media
  (shutil.rmtree(media_dir) call).
- Independently reproduced: created a directory named exactly like a real
  content-addressed media dir (readme-md-a1b2c3d4_media, no paired .md),
  placed a plausible pandoc-generated file (image1.png) AND a clearly
  human-authored file (my_personal_notes.txt) inside it, then ran
  ingest_inbox. Result: the entire directory, including the human file, was
  deleted. The media_cleanup report only records the directory name under
  removed -- there is no indication a non-media file was inside, and no
  distinct "refused" outcome for the foreign content.
- Design/task relevance: design.md's Decision 8 states the cleanup "can
  never delete a human's file" -- this claim is true at the DIRECTORY-NAME
  level (a directory that doesn't match the content-addressed shape is
  never touched) but not at the FILE level once a directory's name has
  matched. The design's own rationale ("the shape alone is sufficient
  because only this harness's own adapter could have produced it")
  addresses name-collision risk, not the scenario where a human adds a
  file to a directory the harness DID legitimately create and later
  orphans.
- Real-world risk is narrow (a human would need to know or guess the exact
  sha8-suffixed directory name to intentionally or accidentally drop a file
  there), but it is the literal adversarial case both this review and the
  original task description ("this cleanup can never delete a human's
  file") were explicitly testing for, and it is currently untested --
  test_media_cleanup.py's orphan-removal test only has an
  expected-to-be-removed media file (image1.png), never an unrelated file
  asserting protection.
- Recommendation: either (a) accept this as a documented, narrow trade-off
  (the design already leans this direction implicitly) and add a test
  proving/pinning the current behavior so it is a conscious choice, not a
  gap, or (b) refuse (rather than remove) a matched-but-non-paired
  directory if it contains any file that doesn't look like known media
  content, at the cost of some cleanup effectiveness.

### SUGGESTION-1 -- No per-item exception handling in the media cleanup loop

- Where: src/docs/application/ingest.py, _clean_orphan_media's for loop over
  media_dirs.
- A single problematic entry (the symlink case above, a permission-denied
  directory, or a file locked by another process on Windows) would raise
  and abort the ENTIRE ingest_inbox call, not just fail-and-report that one
  item. Contrast with _ingest_one_safely's existing per-file try/except
  pattern (already in this same file, a few lines away) that keeps the scan
  going after one file's failure. The cleanup loop does not follow that
  established local convention.
- Low real-world likelihood (requires an unusual filesystem condition), but
  cheap to harden and consistent with the file's own existing resilience
  pattern.

## 2. report["media_cleanup"] Shape Change -- Consumer Sweep

Swept for other consumers of the ingest report shape beyond the 2 tests the
apply agent already updated:

- src/docs/application/pipeline.py, stage_ingest (line ~242-250): reads
  report["files"] and report["processed"] only. Confirmed via diff that
  pipeline.py was NOT touched by this branch. No breakage (an added dict
  key never breaks existing key access), but the CLI-facing stage detail
  string (f"{report['processed']} archivos procesados") has zero visibility
  into media cleanup activity -- see SUGGESTION-2.
- src/docs/application/collection.py: reads evidence.get("files", []) from
  a completely different config block (config["evidence_sources"]), not the
  ingest report. False lead, no relationship.
- tests/unit/application/test_ingest_error_isolation.py: indexes
  report["processed"] and report["files"] individually, never does exact
  dict equality against the whole report. Unaffected by the new key,
  confirmed still passing.
- No CLI command or spec/doc example was found presenting a literal
  _detection.json shape that would now be stale (the only two
  exact-equality assertions that existed were the two the apply agent
  already fixed).

### WARNING-2 -- Report field naming deviates from the literal task/design wording without a disclosed rationale

- Where: tasks.md task 6.2 and design.md's Decision 8 both say refused
  items are "reported in _detection.json.ignored" (a field literally named
  ignored). The actual implementation reports them under
  report["media_cleanup"]["refused"] -- a different key, not a top-level
  ignored array.
- Substance is satisfied (refused items ARE written into _detection.json,
  never silently dropped), so this is not a functional gap. But it is an
  undisclosed deviation from the literal task/design text: apply-progress
  in tasks.md documents the media_cleanup field shape and the exact-equality
  test updates in detail, but never explains why the field is named
  media_cleanup.refused instead of the ignored field the design text names.
- Plausible, defensible reason (not stated in apply-progress): Front C
  (Phase 7, not yet implemented) is expected to introduce its own shared
  "ignored" field for skipped _-prefixed/assets/ items during the recursive
  walk (per design.md Decision 2); pre-empting that with a generically-named
  ignored field now, only to reconcile it with Front C's later, could create
  churn. If that is the real reason, it should be stated explicitly rather
  than left for a reviewer to infer.
- Recommendation: add a one-line note to apply-progress (or a task-list
  annotation) explaining the deviation, and flag it for Front C's own
  apply-progress to reconcile (or explicitly keep separate) when that front
  lands.

## 3. doctor.py De-hardcode Correctness

Read src/docs/application/doctor.py:38-55: the check is correctly gated
inside the pre-existing if config["paths"].get("extracted_dir"): block
(unchanged by this diff), mirrors _check_extracted_dir_policy's own
conditional/consistency shape exactly (bool(extracted_dir_policy) and
isinstance(extracted_dir_policy, str) -- presence/shape only, never an
expected value comparison). Not a weakened check: it still fails when the
field is absent or not a string, so it does not "pass everything."

Independently reproduced against the REAL reporte-estadia-tic.json fixture
(loading the fixture and evaluating the exact expression the code uses):
extracted_dir_policy resolves to "rules_traceability_only", check result is
True. documento-generico has no paths.extracted_dir, so the whole check
block is skipped -- correct conditional behavior for both real fixtures.

### WARNING-3 -- No automated test drives this check against the real reporte-estadia-tic.json fixture

- Where: tests/integration/test_doctor_service.py's 3 new tests all use the
  synthetic _config() helper (a minimal hand-built dict) with hand-picked
  values like extracted_dir_policy="anything_else" -- none load
  tests/fixtures/templates/reporte-estadia-tic.json.
- This matters specifically because PR1's CRITICAL-1 (already fixed) was
  caused by exactly this pattern: a template-declared field resolved
  correctly under synthetic unit-test parameters while silently regressing
  for the real, currently-shipping reporte-estadia-tic fixture, undetected
  until an adversarial fresh-context pass loaded the real file. This PR2
  fix has the identical shape (a .get()-sourced, template-declared field
  feeding a presence check) but was not given the same real-fixture-driven
  regression test PR1's own fix batch added for normative_source and
  pdf_and_extracted_use (see tests/integration/test_evidence_service.py's
  test_build_rules_reporte_estadia_tic_preserves_its_declared_normative_source
  pattern).
- The check IS currently correct for the real fixture (verified above by
  direct reproduction), so this is not a live bug -- but there is no
  regression guard: if reporte-estadia-tic.json's extracted_dir_policy were
  ever accidentally removed or emptied, no test in this diff would catch
  the doctor check silently starting to fail (or, worse, a future edit to
  the check logic could silently stop firing for the real document type
  with nothing catching it).
- Recommendation: add one test in the style of
  test_documento_generico_acceptance.py or PR1's CRITICAL-1 fix, driving
  DoctorService.run_doctor against the real, loaded reporte-estadia-tic.json
  fixture and asserting the extracted_dir_traceability_only check passes.

## 4. Guard Scope Disposition (specifically requested judgment)

The apply agent deliberately did NOT extend
tests/unit/test_no_document_type_literal.py's scan scope to
application/doctor.py, documenting the rationale inline: design.md
Decision 10.2 scopes the guard to domain/rules.py + domain/normative.py
specifically, and doctor.py is a different architectural layer, matching
the same disposition already given to domain/evidence.py's
pdf_and_extracted_use in the PR1 verify report.

Judgment: the rationale PARTIALLY holds as a process argument, but is
WEAKER than presented as an architectural one.

- As a PROCESS argument, it is sound: silently widening a structural
  enforcement test's file scope inside an unrelated bugfix commit is
  exactly the kind of undisclosed scope change a reviewer should be
  suspicious of. Deferring it to a separately-reviewable decision, and
  documenting that deferral inline in the guard's own docstring, is
  disciplined and traceable. This part of the rationale holds.
- As an ARCHITECTURAL argument, different layer therefore out of scope is
  weaker than presented. The guard's own module docstring and the spec
  requirement it enforces (Universal-Schema Policy Contract -- ALL
  document-type policy MUST be declared as template data, never hardcoded,
  anywhere in domain code) were written when only domain/rules.py plus
  domain/normative.py were KNOWN to contain the hardcoded-literal
  anti-pattern, per explore.md's original inventory. That inventory is now
  demonstrably incomplete: the same anti-pattern has been found and fixed
  TWICE outside that scope in two different application-layer files
  (domain/evidence.py's pdf_and_extracted_use in PR1,
  application/doctor.py's extracted_dir_policy comparison in this PR2
  batch) -- both by adversarial review, not by the original design
  inventory. Two independent recurrences outside the guard's stated scope
  is evidence the anti-pattern is not confined to domain code as a layer,
  but recurs wherever a document-type policy value is consumed, regardless
  of layer. Design.md's Decision 10.2 was a reasonable snapshot of known
  risk at design time, not a principled claim that hardcoding is only a
  domain-layer concern.
- Verdict: the guard's CURRENT scope decision is acceptable to leave
  unresolved for this specific PR2 batch, consistent with the process
  discipline above, but the different-architectural-layer framing should
  not be treated as a closed architectural argument going forward. Recommend
  a dedicated follow-up task, not blocking PR2, to either widen the guard to
  cover application services that read template-declared policy fields, or
  to explicitly accept the narrower domain-only scope with a reason stronger
  than layer membership alone -- especially before Fronts C-G add more
  application-layer consumers of template-declared policy.

## 5. Slice Discipline + Spec Traceability

- Diff-stat confirms only 2 non-tasks.md files touched:
  src/docs/application/ingest.py and src/docs/application/doctor.py, plus
  their tests and the no-literal-guard's docstring update. No Front C-G
  files present -- no rglob/recursive walk, no IngestArtifactWriter
  port/adapter, no source_role.py, no near_duplicate.py, no
  figure_catalog.py, no template_validation.py, no
  cli/commands/template_app.py. Confirmed by reading the full ingest.py
  diff directly: only the _clean_orphan_media addition and its wiring into
  the report dict; iterdir() was NOT replaced with rglob(). Slice
  discipline is intact.
- Phase 6's 4 tasks (6.1-6.4) map cleanly onto real code: 6.1/6.2 are the
  new tests in test_media_cleanup.py (both spec-scenario-cited and
  independently confirmed to test genuine behavior, not just the happy
  path), 6.3 is _clean_orphan_media plus its report wiring, 6.4
  (determinism suite x2) is independently confirmed by this review's own
  two full-suite runs.
- Spec traceability: both cited spec scenarios under Orphan Media Directory
  Cleanup (document-ingest capability) -- Re-ingesting a source removes its
  stale media directory, and Referenced media is never deleted -- are
  genuinely covered by real, passing tests, not just cited.
- Determinism: media_dirs iteration is explicitly sorted before processing
  (stable ordering regardless of filesystem iteration order); the report is
  written via json.dumps with sort_keys=True and indent=2, no timestamps or
  randomness, matching the established pattern elsewhere in this file.
  Confirmed via direct code read and via this review's own two-run
  full-suite determinism check.

## Independent Re-run Evidence (this pass)

- Full suite run twice independently: 961 passed, 0 failed, 7 skipped both
  times, byte-identical counts.
- ruff check: 16 errors on this branch. Compared against CURRENT main
  (post PR1 merge, commit d7ad6b5 tree) via a disposable git worktree
  (added and removed cleanly, never touching the live working tree) --
  also 16 errors, identical file:line violation set. 0 net new.
- mypy on the 2 touched src files (doctor.py, ingest.py): no issues found.
- Isolated run of the media cleanup, doctor service, no-literal guard, and
  ingest service/determinism suites (34 tests): all pass.
- Independently reproduced 5 adversarial media-cleanup scenarios directly
  against IngestService (not just reading the diff): paired-md-preserved,
  foreign-shaped-dir-refused, uppercase-hex-refused, short-hash-refused,
  and foreign-file-inside-orphan-destroyed. Confirmed the doctor.py check's
  behavior against both real fixtures (reporte-estadia-tic.json passes,
  documento-generico.json's check is skipped entirely) via direct
  expression evaluation.
- No checkout-main-onto-live-tree mistake was made during this review; all
  main-baseline comparisons used a disposable git worktree add/remove, per
  the coordinator's explicit instruction and this change's own two prior
  incidents.

## Issues Summary

| Severity | Count | Items |
|----------|-------|-------|
| CRITICAL | 0 | none |
| WARNING | 4 | foreign file inside orphan dir destroyed; refused-items field naming deviates from task/design wording undisclosed; doctor.py fix lacks real-fixture test; guard scope rationale weaker than presented |
| SUGGESTION | 2 | no per-item exception handling in cleanup loop; CLI stage_ingest has zero visibility into media cleanup activity |

## SUGGESTION-2 -- CLI-facing ingest stage detail has no visibility into media cleanup activity

stage_ingest's detail string only reports processed/error counts from
report["files"] and report["processed"]; a user running the pipeline never
sees how many stale media directories were cleaned or refused, even though
this information is now computed on every ingest run and written to
_detection.json. Not a spec violation (no scenario requires CLI surfacing),
but worth considering for a future front's UX pass.

## Verdict

needs-fixes -- no CRITICAL findings, and the two live-behavior claims
(media cleanup correctness for the tested cases, doctor.py check
correctness) are independently confirmed accurate. All 4 WARNINGs are
narrow, independently fixable, and none indicate a fundamental design flaw:
WARNING-1 (foreign file in orphan dir) is the most substantive and worth a
conscious decision before merge; WARNING-2 (field naming) and WARNING-3
(missing real-fixture test) are process/coverage gaps with low current
risk; the guard-scope finding is a documentation/framing note for a future
task, not a defect in this PR2 batch itself.

---

# Re-verification (fix batch: 0170726, a8d4091, b5c536c, fc739b4, f5d3a47)

Second fresh-context pass on PR2, targeted at closing the findings above. No
code was changed by this review; only this report was appended to
(working-tree only, not committed by this agent).

## Per-finding status

| Finding | Status | Evidence |
|---------|--------|----------|
| WARNING-1 (foreign file inside orphan dir destroyed) | FIXED | Re-ran the exact original data-loss reproduction (same directory name, same image1.png plus my_personal_notes.txt, no paired .md). Directory, image, and foreign file all now survive. media_cleanup reports it under refused with a cause naming the offending file. Adversarially probed further: zero-byte whitelisted-extension files are treated as expected (deleted, harmless); a nested media subfolder with a recognized extension is still cleaned up correctly (no over-refusal of genuine pandoc output); an unlisted-but-plausible extension (.eps) is safely over-refused with a sane cause; extension matching is case-insensitive (.PNG treated as .png); multiple offending files report the alphabetically-first one deterministically (sorted traversal). One residual, low-severity gap found -- see NEW-SUGGESTION-3. |
| SUGGESTION-1 (no per-item exception isolation) | FIXED | The cleanup loop now wraps each directory's processing in try/except OSError; a monkeypatched shutil.rmtree raising for one directory (simulating the symlink case) leaves that directory refused with the OS error as cause while a second, unrelated orphan directory in the same scan is still cleaned up normally -- confirmed via the new test and independently re-verified by reading the code path. |
| WARNING-3 (doctor.py fix lacked a real-fixture test) | FIXED, and confirmed MEANINGFUL | Two new tests drive DoctorService.run_doctor against the real reporte-estadia-tic.json (check passes) and documento-generico.json (check absent) fixtures. Independently confirmed meaningfulness: loaded the real fixture, deleted paths.extracted_dir_policy from the in-memory dict only (no file touched), and re-ran run_doctor -- the check flips to False, proving this test would genuinely catch a real regression in the fixture, not just exercise a code path. |
| WARNING-2 (undisclosed field-naming deviation) | FIXED | An additive clarification blockquote was added to design.md's Decision 8, explicitly stating the refused field's name/shape deviates from the literal _detection.json.ignored wording and why (avoiding a shape collision with Front C's future shared ignored field, plus the richer {path, cause} shape now being load-bearing for WARNING-1/SUGGESTION-1). Confirmed via diff this is a pure addition -- no original prose was rewritten or deleted. |
| WARNING-4 (guard-scope rationale weaker than presented) | FIXED (documentation follow-up, as recommended) | A new, unchecked task 13.1 was added under a new Phase 13: Hardening follow-ups section in tasks.md, recording the two real occurrences outside the guard's scope and framing the decision as needing deliberate re-evaluation before Fronts C-G, not resolved silently. This matches exactly what this review's original judgment recommended (a dedicated follow-up task, not a silent scope change). Confirmed the guard's actual scan scope (rules.py + normative.py) was NOT touched by this fix batch -- the disposition itself remains open, as intended. |
| SUGGESTION-2 (CLI stage_ingest has no media-cleanup visibility) | FIXED | stage_ingest now appends "; media: N eliminado(s), M rechazado(s)" (Spanish, matching project convention) to its detail string when there is any cleanup activity, and omits it entirely when there is none (verified via two independent tests, both re-run and passing). |

## Coordinator-flagged risk: media_cleanup.refused shape change (list[str] to list[{path,cause}])

Swept src/ for every consumer of the ingest report's media_cleanup field:

- src/docs/application/pipeline.py, stage_ingest: only reads
  len(media_cleanup.get("removed", [])) and len(media_cleanup.get("refused",
  [])) -- a count, never the item shape. Unaffected by the change from
  strings to dicts.
- No other src/ consumer of media_cleanup exists (confirmed by a direct
  grep across src/).
- Test-side: the one pre-existing test asserting the old bare-string shape
  (test_foreign_non_content_addressed_media_dir_is_refused_not_deleted) was
  updated in the same commit that introduced the shape change. The two
  older tests asserting the field's presence with EMPTY lists
  (test_ingest_service.py, test_ingest_determinism.py) are shape-agnostic
  for an empty list and remain correct unmodified -- confirmed still
  passing.
- Verdict: the shape change is genuinely harmless. No missed consumer found.

## Coordinator-flagged risk: ruff 15 vs main's 16

Independently confirmed via a disposable git worktree comparison (never
touching the live tree): the CURRENT branch's ruff output has exactly the
same 15 violations as main's 16 MINUS
tests/integration/test_doctor_service.py:5:21 F401 (pathlib.Path imported
but unused). WARNING-3's fix added real code using Path (_FIXTURES_DIR =
Path(__file__)...) in that same file, which revives the previously-dead
import. Every other violation (file:line pair) is identical between this
branch and main. This is a genuine, incidental, purely beneficial side
effect -- not a masked new violation, not scope creep, not a red flag.

## New findings from this pass

### NEW-SUGGESTION-3 -- An empty nested subdirectory inside an orphan media dir is silently swept away with no distinct reporting

- Independently reproduced: created an orphan-shaped media dir with one
  valid image file plus one EMPTY nested subdirectory (no files inside it
  at all). The whole directory, including the empty subfolder, was removed
  -- _first_unexpected_media_file only inspects files (path.is_file()), so
  an empty directory never trips the unexpected-content check.
- Severity: very low. An empty directory holds no actual data to lose (no
  bytes, no content), so this is a much narrower residual version of the
  original WARNING-1 gap, not a new instance of real data loss. Still,
  strictly speaking it means "a human-created directory structure" (even
  if empty) can be silently absorbed into a cleanup pass without being
  reported.
- Not blocking. Worth a one-line mention in a future hardening pass if
  Phase 13's task 13.1 (or a sibling task) revisits this area, but not
  worth its own task given the near-zero practical impact.

## Independent Re-run Evidence (this pass)

- Full suite run twice independently: 968 passed, 0 failed, 7 skipped both
  times, byte-identical counts. Matches the claimed count exactly.
- ruff check: 15 errors on this branch, confirmed via a disposable git
  worktree against current main (16 errors) -- the exact single-item
  reduction described above, nothing else different.
- mypy on all 3 touched src files (ingest.py, doctor.py, pipeline.py): no
  issues found.
- Isolated run of the media cleanup (7 tests), doctor service (14 tests),
  and pipeline media-cleanup-surfacing (2 tests) suites: all pass.
- Independently re-ran the exact original WARNING-1 reproduction script
  (unchanged from the original verify pass) against the fixed code: the
  foreign file and the directory both now survive, with a correctly-worded
  refusal cause.
- Independently probed 5 additional adversarial dimensions of the new
  content-inspection logic beyond the original findings (zero-byte files,
  nested legitimate media, over-refusal safety, case sensitivity,
  first-offender determinism) -- all behave safely and sanely; found one
  new, very-low-severity residual gap (NEW-SUGGESTION-3).
- No checkout-main-onto-live-tree mistake was made during this review; all
  main-baseline comparisons used a disposable git worktree add/remove.

## Re-verification Verdict

ready-for-pr -- all 6 original findings (0 CRITICAL, 4 WARNING, 2
SUGGESTION) are genuinely, verifiably closed with real tests and, where
applicable, independently-reproduced adversarial evidence, not performative
fixes. Both coordinator-flagged risks (media_cleanup.refused shape change,
ruff 15-vs-16) are confirmed harmless. One new, very-low-severity
suggestion (empty nested subdirectory silently swept) is noted for a future
hardening pass, not blocking.
