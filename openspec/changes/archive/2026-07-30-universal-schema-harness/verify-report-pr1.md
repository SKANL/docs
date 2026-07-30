# Verify Report -- PR1 (Front A: policy de-hardcoding + first-use bug fixes)

Change: universal-schema-harness | Branch: feat/usch-a-policy-dehardcode
Scope: Phases 1-5 only (characterization net + Front A). Fronts B-G
(Phases 6-12) intentionally not implemented -- not evaluated here except
for slice-discipline leakage.
Reviewer: sdd-verify (fresh-context adversarial review)

## Executive Summary

Front A is functionally sound and well-tested (942/942 tests pass twice in a
row, ruff/mypy baselines unchanged, real acceptance-gate + characterization
tests genuinely exercise the claimed behavior) -- but PR1 as committed carries
1 CRITICAL silent regression (build_manifest's normative_source drops
to an empty string for the real reporte-estadia-tic fixture, uncaught by any
test), 3 WARNINGs (structural no-literal guard has quote/value-format bypass
gaps; a hardcoded literal remains in domain/evidence.py outside the guard's
scan scope; spec.md wording for the extracted-dir scenario doesn't match the
two-function implementation split), and 3 SUGGESTIONs (missing unit test for
one conditional check's silence, diff-size-over-forecast is justified but
worth calling out, isinstance(x, (int, float)) margin check accepts bools).
Verdict: needs-fixes -- the CRITICAL item should be resolved (or explicitly
accepted with a documented rationale) before push+PR.

## 1. Acceptance Gate

- uv run pytest -- 942 passed, 0 failed, 7 skipped, run twice
  independently by this review; byte-identical pass/fail counts both times.
  Confirms the apply-progress claim.
- documento-generico passes doctor/review-rules/build-rules with zero
  errors -- verified via tests/integration/test_documento_generico_acceptance.py
  (3 tests, all pass in isolation): review_rules zero issues,
  build_rules succeeds and reports skipped_paths == {manual_dir,
  extracted_dir} (not a crash, not silently dropped), and doctor's
  rules_config check passes. This is a genuine integration test against the
  real fixture file, not a manual assertion.
- ruff check . -- 16 errors, confirmed identical on main (checked via
  a disposable git worktree against main, not by mutating the working
  tree) and on this branch. 0 net new.
- mypy on the five touched src files (rules.py, normative.py, evidence.py
  domain+application, documents.py) -- no issues found.

## 2. Characterization Honesty

Verified via git log --follow and a direct diff between commit 73d5433
and HEAD (c77bd4d) for tests/unit/domain/test_rules_characterization.py:
the file was authored once, in commit 73d5433 (Phase 1, before any
rules.py/normative.py edit), and is byte-identical from that commit through
HEAD -- zero diff. Additionally ran the file at commit 73d5433 in a
disposable worktree: 3/3 pass against the pre-refactor rules.py,
confirming the snapshots genuinely capture pre-existing behavior rather than
being reverse-engineered from the new code. This is an honest
characterization net -- the byte-identical claim for review_rules and
review_section_text on reporte-estadia-tic is TRUE and test-proven.

Caveat (see CRITICAL-1 below): the characterization net's scope is
narrower than the "byte-behavior-identical" language in tasks.md and
apply-progress implies -- it covers only review_rules and
review_section_text, not build_manifest, so a real behavior change in
manifest generation slipped through undetected.

## 3. No-Literal Guard Effectiveness

tests/unit/test_no_document_type_literal.py does correctly fail before the
Phase 3/4 edits and pass after (confirmed by reading the file's own docstring
and the task history; the guard scans rules.py + normative.py source via
inspect.getsource). However, adversarial analysis of the banished-literal
list found real bypass gaps -- see WARNING-1 below.

## 4. Rewritten Test Fidelity

Spot-checked all ~10 rewritten tests in tests/unit/domain/test_rules.py
against their cited spec scenarios:

- The generic/estadia extra split matches spec "Optional-Block Absence
  Semantics" -- confirmed each converted check has a "stays silent" test
  using the generic baseline for 3 of 4 conditional checks (see
  SUGGESTION-1 for the 4th).
- test_review_rules_apa7_disabled_is_not_forced_and_raises_no_issue --
  matches spec "APA gate respected" exactly (asserts absence of the deleted
  literal-comparison message, result.passed is True).
- The four "any declared value accepted" tests (extracted_dir_policy,
  body_pagination_start section id, margins, cover_policy) each correctly
  prove "no hardcoded literal" by using a value that would have FAILED under
  the old hardcoded check and asserting it now passes. This is the right
  assertion shape (not just renamed, genuinely re-targeted).
- The APA contract-level test correctly asserts the deleted document-level
  duplicate issue no longer fires, only the contract-level one remains --
  matches the _check_apa7_enabled deletion rationale.

No fabricated or mismatched spec citations found in the sample reviewed.

## 5. Correctness Findings

### CRITICAL-1 -- normative_source silently regresses to an empty string for the real reporte-estadia-tic fixture, uncaught by any test

- Where: src/docs/application/evidence.py line 123 --
  normative_source=config.get("normative", {}).get("normative_source", "")
- Evidence: tests/fixtures/templates/reporte-estadia-tic.json's normative
  block only declares excluded_front_matter, first_person_patterns,
  subjective_terms -- it never declares normative_source. Reproduced
  directly by loading the fixture JSON and evaluating the exact expression
  from application/evidence.py:123 -- result is an empty string.
- Before this PR: domain/evidence.py's build_manifest hardcoded
  normative_source to "docs/guides/manual-estadia-tic" for every document
  type. This was WRONG for other types (the bug this PR legitimately fixes,
  #7 in explore.md) but happened to be the CORRECT, real value for
  reporte-estadia-tic -- it matches that template's own paths.manual_dir.
- After this PR: running build-rules on the real reporte-estadia-tic
  template now writes an empty normative_source into manual-rules.json -- a
  real, silent loss of previously-correct information for an existing,
  currently-shipping document type.
- Why no test caught it: the characterization net (task 1.1) only snapshots
  review_rules/review_section_text, not build_manifest. The new
  test_build_manifest_normative_source_* tests in
  tests/unit/domain/test_evidence.py use a synthetic call builder with
  hand-picked parameters, never loading the real fixture. No integration
  test builds the manifest for reporte-estadia-tic and asserts
  normative_source.
- Spec relevance: this isn't a formally-scenario'd requirement (no spec.md
  scenario literally says reporte-estadia-tic's normative_source must be
  preserved), so it doesn't fail the Decision-Gate's "untested scenario"
  rule literally -- but it does violate the proposal/design's stated
  migration philosophy (design.md Decision 10: "the two existing fixtures
  become the acceptance tests... reporte-estadia-tic must stay
  byte-behavior-identical") in spirit, for a field the design's own
  Decision 10.3 introduced.
- Fix options: (a) backfill normative.normative_source into the
  reporte-estadia-tic.json fixture (mirrors what Decision 1d already did
  for the lexicons), or (b) if the loss is intentionally accepted, state
  that explicitly in apply-progress rather than implicitly relying on an
  out-of-scope characterization net. Either way this needs a conscious
  decision, not a silent gap.

### WARNING-1 -- No-literal structural guard has quote-style and bare-value bypass gaps

- Where: tests/unit/test_no_document_type_literal.py, the banished-literal
  list (lines 22-37).
- The "introduccion" literal is banned only in its double-quoted source
  form. Re-introducing the same hardcoded comparison with single quotes
  would produce source text that does NOT contain the banned double-quoted
  substring -- the guard would silently miss it.
- The margin literal is banned only as the constant name
  (_EXPECTED_MARGIN_CM), not the value it held (2.5). Re-introducing a
  hardcoded comparison like abs(val - 2.5) > 0.001 inline (without
  recreating the named constant) would not match any banished literal and
  would silently bypass the guard.
- Impact: the guard is a real enforcement mechanism today (proven to
  fail-then-pass across the Phase 3/4 commits), but it is not robust against
  a differently-formatted reintroduction of the same policy literals -- a
  plausible way for a future contributor (or AI agent) to accidentally
  reintroduce exactly the hardcoding this front removes.
- Recommendation: add a regex-based scan, or ban both quote-style variants
  of section-id literals, as a follow-up hardening task.

### WARNING-2 -- A hardcoded document-type literal remains in domain/evidence.py, outside the guard's scan scope

- Where: src/docs/domain/evidence.py line 47 --
  "pdf_and_extracted_use": "rules_traceability_only" (unconditional,
  written into every manifest regardless of template).
- This literal was NOT in explore.md's inventory (#1-13) and is not covered
  by test_no_document_type_literal.py (which only scans rules.py +
  normative.py, per Decision 10.2's explicit scope).
- specs/document-template/spec.md's "Universal-Schema Policy Contract"
  requirement states unqualified: "ALL document-type policy MUST be
  declared as template data" -- broader than what Front A actually
  enforces. The narrower scenario ("No hardcoded document-type literal in
  domain code") says "none are found in policy-check code paths", which
  arguably excludes this (it is manifest metadata, not a rules.py check),
  so this is likely an accepted, pre-scoped gap rather than an oversight --
  but the completion claim "no hardcoded document-type literal in domain
  code" is not literally 100% true for domain/ as a whole. Flagging for
  visibility, not blocking (this exact literal was never claimed as fixed
  by Phases 1-5).

### WARNING-3 -- spec.md wording for "Extracted-dir policy checked only when configured" does not match the two-function split

- Where: openspec/changes/universal-schema-harness/specs/document-pipeline/spec.md
  lines 32-38 versus src/docs/domain/rules.py lines 330-367
  (_check_extracted_dir_policy plus _check_source_priority_excludes_extracted).
- The spec scenario's final line reads: "...the check verifies the declared
  policy string is internally consistent with source_priority." The actual
  implementation is two independent checks that never cross-reference each
  other: one validates a policy string is declared (shape-only), the other
  validates source_priority does not include the declared extracted_dir
  path (unrelated to the policy string's value). Neither check does what
  the spec's literal sentence describes.
- design.md's Decision 1a table (the authoritative decision record) is
  correctly split into two separate rows and the implementation matches
  design.md faithfully -- this is a spec.md wording issue, not an
  implementation bug. Recommend tightening spec.md prose to match
  design.md's actual two-check breakdown.

## 6. Slice Discipline

Confirmed via a diff-stat between main and HEAD: only 13 non-tasks.md files
touched, all within Front A / first-use-bugs scope declared in the apply
progress (rules.py, normative.py, evidence.py domain+application,
documents.py inbox-dir addition, plus their tests + 3 new test files).
No Front B-G files present -- no application/ingest.py, domain/source_role.py,
domain/near_duplicate.py, domain/figure_catalog.py,
domain/template_validation.py, cli/commands/template_app.py, or any
inbox/_*.json writer/port. documents.py's inbox/ plus inbox/assets/
addition is pure directory bootstrap (no routing/ingest logic), correctly
scoped to Phase 5.5-5.6 per design.md Decision 8's explicit call-out that
bootstrap owns _SUBDIRS even though inbox/assets/ content is Front F's
concern. Slice discipline is intact.

Diff size: 1115 insertions / 147 deletions across 14 files including
tasks.md (207 lines, non-code); excluding tasks.md the code+test diff is
roughly 908 insertions / 147 deletions, about 1055 lines total, above the
~700-900 forecast in tasks.md's Suggested Work Units table. The overage is
attributable almost entirely to the 361-line test_rules_characterization.py
snapshot file (SUGGESTION-2) -- a low-cognitive-load, high-value
regression-safety addition, not scope creep. Acceptable, worth noting in
the PR description.

## 7. Task/Spec Completeness

All 22 checked tasks (Phases 1-5) in tasks.md correspond to real, verifiable
code changes -- no checkbox found to be aspirational or unsupported by the
diff. Extra work beyond the numbered tasks
(test_documento_generico_acceptance.py, commit 77f7ecd) is called out
explicitly in the apply-progress as "beyond numbered tasks" and is a
legitimate strengthening of the falsifiable acceptance gate, not undisclosed
scope creep.

## Issues Summary

| Severity | Count | Items |
|----------|-------|-------|
| CRITICAL | 1 | normative_source regression for reporte-estadia-tic |
| WARNING | 3 | no-literal guard bypass gaps; residual literal in evidence.py; spec.md wording mismatch |
| SUGGESTION | 3 | missing unit test for source_priority silence; diff-size note; bool-accepted-as-numeric margin edge case |

## SUGGESTION-1 -- _check_source_priority_excludes_extracted lacks a dedicated "silent when extracted_dir absent" unit test

Phase 2.3 added explicit silence tests for 3 of the 4 conditional checks
(extracted_dir_policy, preliminaries_pagination, margins_and_cover_policy)
but not for _check_source_priority_excludes_extracted. Currently only
covered indirectly via the documento-generico acceptance-gate integration
test. Add a direct unit test for symmetry with the other three.

## SUGGESTION-2 -- Diff-size overage attribution

Already covered in Section 6 -- no action required, just flag in the PR
description so reviewers are not surprised by the >900-line forecast miss.

## SUGGESTION-3 -- Margin numeric check accepts Python bools

The isinstance(value, (int, float)) check in _check_margins_and_cover_policy
(rules.py line 408) also accepts True/False since bool subclasses int in
Python. Pre-existing pattern (not newly introduced by this diff), low
real-world risk since no template would plausibly declare a margin as a
boolean, but worth a follow-up hardening note if template validate
(Front G) reuses this pattern.

## Verdict

needs-fixes -- CRITICAL-1 should be resolved (backfill the fixture value or
explicitly document the accepted loss) before push+PR. WARNINGs 1-3 are
non-blocking but should be triaged (WARNING-1 especially, since it weakens
the enforcement mechanism this front exists to establish).

## Incident Note (process, not code)

During this review, an errant "git checkout main -- ." was run against the
live working tree while attempting to compare ruff baselines, briefly
overwriting several tracked files with main's versions. This was caught
immediately (before any test run against the corrupted state) and fully
reverted via "git checkout HEAD -- ." plus "git stash pop" (the untracked
openspec/ planning files had been stashed first and were restored intact).
Verified via an empty diff-stat against HEAD and a full pytest run (942
passed) that the working tree was fully restored before continuing the
review. All ruff-baseline comparisons were subsequently redone safely via a
disposable git worktree rather than mutating the working tree. No commits,
pushes, or state.yaml changes were made by this review.

---

# Re-verification (fix batch: d75ee83, ff159ad, cef4b67, a93acd0, cdad98c)

Second fresh-context pass, targeted at closing the findings above. No code
was changed by this review; only this report was appended to (working-tree
only, not committed by this agent).

## Per-finding status

| Finding | Status | Evidence |
|---------|--------|----------|
| CRITICAL-1 (normative_source regression) | FIXED | Re-ran the exact original reproduction expression against the real reporte-estadia-tic.json -- now returns "docs/guides/manual-estadia-tic", not an empty string. Fixture backfilled with normative.normative_source (mirrors Decision 1d's lexicon backfill pattern). New REAL-fixture-driven integration test plus a build_manifest policy-block snapshot added to the characterization net, closing the exact scope gap that let the original regression slip through. |
| WARNING-2 (pdf_and_extracted_use hardcoded literal, plus reuse-coupling judgment) | FIXED, reuse is SOUND | See judgment below. |
| WARNING-1 (no-literal guard bypass gaps) | FIXED | Re-tried both original bypasses: a single-quoted section id literal and a bare margin value without the named constant. Both now caught -- the banned-literal list was changed from a quote-wrapped entry to a bare, quote-agnostic substring, and a bare numeric entry was added alongside the constant-name entry. New synthetic-source tests prove both catches without touching production code as the fixture. Ran the guard test file directly: 5 passed. |
| WARNING-3 (spec.md wording vs. two-function split) | FIXED | An additive clarification blockquote was inserted under the relevant scenario in specs/document-pipeline/spec.md, explaining the scenario is satisfied by two independent, non-cross-referencing check functions per design.md Decision 1a. Original scenario prose was NOT rewritten (respects the frozen-planning-artifact, additive-only convention). |
| SUGGESTION-1 (missing silence test for source_priority check) | FIXED | A silence test was added, asserting an empty result even when source_priority is populated, as long as extracted_dir is absent -- correct symmetry with the other 3 conditional-check silence tests. |
| SUGGESTION-3 (bool accepted as numeric margin) | FIXED | The margin check now explicitly excludes bool before the int/float check. A new test sets a margin to a boolean and asserts it is rejected. |

## WARNING-2 reuse judgment (specifically requested)

The fix sources build_manifest's pdf_and_extracted_use parameter from the
same field, paths.extracted_dir_policy, that _check_extracted_dir_policy in
rules.py validates (must be a declared non-empty string when
paths.extracted_dir is set).

Verdict: this reuse is semantically sound, not a coupling smell.

Reasoning:
- Historically, before this PR, both fields were independently hardcoded to
  the identical literal string for the same estadia-only policy -- two
  separate copies of the same policy statement that had to be manually kept
  in sync (and coincidentally were, since nobody had touched either in
  isolation). Sourcing pdf_and_extracted_use from extracted_dir_policy
  replaces an implicit, duplicated invariant with an explicit, single
  source of truth -- a strict improvement over the prior state, not a new
  risk.
- The two consumers read the same field for the same underlying concept:
  what is the declared policy governing extracted/traceability content.
  _check_extracted_dir_policy validates the field is present and
  well-shaped; build_manifest surfaces its value for audit/evidence
  purposes. There is no case where these two would legitimately need
  different values for the same template -- they are two views onto one
  policy declaration, not two independent policies that happen to share a
  name.
- Checked for functional coupling risk: grepped src/ for the field name --
  it is written into the manifest and never read back by any check or gate.
  It is purely informational/audit metadata, so even if the reuse were ever
  judged wrong for a future document type, the blast radius is limited to a
  manifest field's display value, not a behavioral gate.
- documento-generico (no extracted_dir_policy declared) correctly resolves
  to an empty string for both fields -- verified via a new
  real-fixture-driven test. No value is invented for a document type that
  never declared one.
- Minor naming note (non-blocking): the field name suggests it could also
  describe manual_pdf/example_pdf usage, not just extracted_dir usage, but
  no separate field exists for that narrower concept and none was ever
  hardcoded for it either -- the field has always meant the
  traceability-use policy, and extracted_dir_policy is exactly that
  policy's template-declared home. The added code comment already states
  this sourcing explicitly, which is sufficient documentation.

## New findings from this pass

### NEW-SUGGESTION-1 -- doctor.py has a sibling hardcoded literal, untouched by this branch

- Where: src/docs/application/doctor.py line 43 -- a hardcoded comparison
  of paths.extracted_dir_policy against the same fixed estadia-only policy
  string.
- Confirmed via git log that doctor.py was NOT touched anywhere in this
  branch (last modified by an unrelated pre-existing commit, 11a92e0). This
  literal predates PR1 entirely and is a sibling of the exact class of bug
  WARNING-2 just fixed in domain/evidence.py -- doctor.py's rules_config
  check still hardcodes the expected policy value instead of just checking
  presence/shape, the way rules.py's own _check_extracted_dir_policy now
  does.
- Not blocking for PR1 (out of its diff, out of explore.md's original
  inventory, and out of this targeted re-verification's requested scope),
  but flagging for a future front/task since it is the same category of
  hardcoding this whole change exists to remove.

## Independent re-run evidence (this pass)

- Full test suite run twice independently: 954 passed, 0 failed, 7 skipped
  both times, byte-identical counts.
- ruff check: 16 errors, identical set of file:line violations confirmed
  against the main-baseline comparison already established in the original
  review (0 net new).
- mypy on the five touched src files: no issues found.
- Isolated run of the acceptance gate, characterization net, no-literal
  guard, and evidence/rules unit suites (162 tests): all pass.
- Confirmed the original two review_rules/review_section_text
  characterization tests (byte-identical since commit 73d5433) still pass
  unmodified, and the new build_manifest policy-block snapshot added in
  this fix batch also passes against the real fixture.
- Confirmed no code was touched outside the fix-batch's own stated scope:
  documento-generico.json and its acceptance test are untouched.

## Re-verification Verdict

ready-for-pr -- all 6 original findings (1 CRITICAL, 3 WARNING, 2
SUGGESTION addressed directly; SUGGESTION-2 required no action per the
original report) are genuinely, verifiably closed with real tests against
real fixtures, not performative fixes. One new, non-blocking suggestion
(doctor.py's sibling literal) is noted for a future task, out of this
branch's diff and out of scope for PR1.
