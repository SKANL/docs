# Verify Report -- PR3 (Front C: recursive ingest + JVM look-ahead status + IngestArtifactWriter)

Change: universal-schema-harness | Branch: feat/usch-c-recursive-ingest
Base: main @ 7fbf044 (merge of PR2, feat/usch-b-bootstrap-media)
Scope: Phase 7 only (9 tasks). Fronts D-G (Phases 8-12) intentionally not
implemented -- not evaluated here except for slice-discipline leakage.
Reviewer: sdd-verify (fresh-context adversarial review, third target in
this change)

## Executive Summary

PR3 is functionally solid: 988/988 tests pass twice, ruff (15, matches
current main exactly) and mypy baselines unchanged. The headline claim --
zero adapter changes needed for correct per-directory JVM batching under
recursion -- was independently, empirically re-verified with a handler that
mirrors OpendataloaderPdfAdapter's exact caching structure, not just trusted
from the diff or the existing fake-handler tests. No CRITICAL findings.
1 WARNING: the self-referential appearance of _detection.json/
_source-manifest.json in their own next scan's ignored list (deliberate,
tested, honest) uses a generic reason indistinguishable from a genuine
user _-prefixed exclusion, which could read as ambiguous to an agent
consumer. 2 SUGGESTIONs: the inbox/assets/ exclusion is correctly
top-level-only (matches design faithfully) but that specific boundary
(nested assets/ folders are walked, not excluded) has no pinning test;
case-sensitive sort ordering is documented but worth a one-line callout
for future readers. Verdict: needs-fixes is too strong given zero
correctness defects found -- ready-for-pr, with the WARNING and
SUGGESTIONs as optional, non-blocking hardening.

## 1. The Untouched-Adapter Claim (empirically re-verified, not just read)

The apply-progress claims OpendataloaderPdfAdapter's existing
_discover_candidates (scoped to seed_src.parent) already implements correct
per-directory batching under recursion with zero adapter changes. Read the
real adapter source directly (src/docs/infrastructure/ingest/
opendataloader_pdf_adapter.py) to confirm the mechanism: _discover_candidates
scans only seed_src.parent, and the constructor-level self._results dict
persists for the adapter instance's whole lifetime.

Rather than trusting this from the diff or the existing fake-handler tests,
built an independent throwaway handler that mirrors the REAL adapter's exact
structure (same self._results cache shape, same seed_src.parent-only
discovery) and drove it through IngestService against a tree with three
directories: two PDFs in dirA, one PDF in dirB, three PDFs in dirC.

Result: exactly 3 _convert_batch invocations (one per directory), each
scoped correctly to its own directory's siblings only -- dirA's batch never
saw dirB's or dirC's files. Statuses were correct in every directory
(first-reached file ingested, siblings batched). A second scan against the
same adapter INSTANCE (reusing its now-populated self._results cache)
produced zero additional _convert_batch calls and all-skipped statuses --
proving IngestService's own pre-scan snapshot check happens BEFORE the
handler is ever invoked, so a stale or populated adapter-level cache poses
no practical hazard even when the same instance serves multiple directories
or multiple scans of the same tree. This independently confirms the
untouched-adapter claim is correct, not just plausible.

## 2. Status Vocabulary Honesty

Confirmed via the existing test_jvm_lookahead_batch_first_sibling_ingested_
second_batched_then_both_skipped_on_rerun (real re-run, not just a single
scan) and independently re-derived with the mirrored-adapter reproduction
above: a file produced mid-scan by a sibling's batch call correctly reads
batched (not ingested, not skipped); a file already present from a prior
run correctly reads skipped; the classification is resolved purely against
a pre-scan snapshot captured once before any conversion, never a live
existence check alone -- so the mechanism is agnostic to WHY an output
appeared (JVM batch side effect vs. an earlier byte-identical file reached
first in sort order), which is the documented, correct generalization.

Determinism: ran the full suite twice myself (988/988 both times,
byte-identical). Independently re-read
test_recursive_walk_report_ordering_is_byte_stable_across_two_independent_
runs, which performs an explicit warm-up scan before comparing scan N to
scan N+1 -- correctly accounting for the one legitimate case where scan 1
differs from all later scans (the artifact files not existing yet). Entries
are confirmed to appear in POSIX-sorted relative-path order (a-dir before
top.md before z-dir), not filesystem iteration order.

## 3. Recursive Walk Correctness (adversarially probed, not just read)

Independently reproduced, beyond what the existing test suite already
covers:

- _-prefix rule at every depth: confirmed via existing tests
  (sub/_drafts/wip.md excluded and reported ignored; a directory whose ONLY
  content is _-prefixed correctly produces BOTH an ignored entry AND an
  empty_dir marker, non-contradictory).
- inbox/assets/ exclusion scope: independently reproduced a NESTED
  docs/assets/cover.png (assets NOT directly under the inbox root). Result:
  it is NOT excluded -- walked as a regular file entry (kind "png", no
  handler registered, so "unsupported"). Cross-checked against design.md
  Decision 2/6's own wording, which consistently describes inbox/assets/ as
  a single, fixed top-level convention path, never a wildcard pattern
  matching any directory literally named "assets" anywhere in the tree.
  This is CORRECT, faithful-to-design behavior, not a bug -- but see
  SUGGESTION-1 below: this specific boundary has no pinning test.
- Accented/unicode filenames (mirroring the real GUIA files): a file named
  with an accented uppercase character sorts and round-trips through
  relative_path/source_dir correctly -- Python's codepoint-based string
  comparison is locale-independent, so this is safely deterministic across
  platforms, not just working by coincidence on this machine.
- Case-sensitive ordering: independently reproduced (an uppercase-leading
  filename sorts before an all-lowercase one) -- confirmed intentional and
  documented (task 7.3, design.md Decision 2: "case-sensitive" POSIX sort,
  chosen specifically to avoid locale-dependent collation differences
  between Windows and Linux). Not a bug; see SUGGESTION-2 for a minor
  documentation note.
- Windows path separator normalization: every relative_path value observed
  in this review's reproductions (run natively on Windows) used forward
  slashes exclusively -- confirms _relposix's .as_posix() call is doing its
  job, not merely appearing correct by accident of the test fixtures.
- Same stem, different subfolders, content-hash disambiguation: confirmed
  via the existing test (two byte-identical readme.md files in different
  subfolders both get distinct relative_path rows, collapse onto the SAME
  content-addressed output path, second is batched this run / skipped on
  rerun) -- collision-free by construction, since the flat sections/
  ingested/ output identity has always been content-hash-only and Front C
  does not change that.
- Deep nesting: the two-level nested test (sub/deep/notes.md) and the
  three-level realistic-drop fixture (guides/manual-estadia-tic/*.md)
  exercise multi-level nesting; no depth limit or recursion-safety issue
  was found reading _walk_inbox (a single non-recursive rglob("*") call,
  not a hand-rolled recursive function, so no stack-depth concern for any
  realistic tree depth).

### WARNING-1 -- Self-referential harness artifacts in the ignored list use the same generic reason as genuine user exclusions, which could read as ambiguous to an agent consumer

- Where: src/docs/application/ingest.py, _walk_inbox's
  _has_underscore_component check (reason "underscore_prefixed").
- Independently reproduced: after a first ingest_inbox scan writes
  _detection.json and _source-manifest.json into inbox_dir, a second scan
  of the SAME inbox reports both files under ignored, each with reason
  "underscore_prefixed" -- the exact same reason value used for a genuine
  user file like sub/_drafts/wip.md.
- This is deliberate and honestly tested (the apply-progress explicitly
  calls it out, and test_recursive_walk_report_ordering_is_byte_stable_
  across_two_independent_runs's warm-up-run comment documents it) -- the
  report never hides these files, so nothing is silently dropped. The
  concern is narrower: an agent or human reading ignored: [{"relative_path":
  "_detection.json", "reason": "underscore_prefixed"}, {"relative_path":
  "sub/_drafts/wip.md", "reason": "underscore_prefixed"}] has no
  machine-readable way to distinguish "this is the harness's own
  bookkeeping, ignore it" from "this is a real file the user chose to
  exclude, maybe worth surfacing to them." The filename alone (a leading
  underscore plus a recognizable name) is the only signal, which requires
  out-of-band knowledge of this harness's specific artifact filenames.
- Recommendation: give the two well-known self-written filenames
  (_detection.json, _source-manifest.json) their own reason value (e.g.
  "harness_artifact") distinct from "underscore_prefixed", so a downstream
  consumer can filter them out mechanically without hardcoding filename
  knowledge. Low priority -- not a correctness defect, a clarity
  improvement.

## 4. Hierarchy-Level Guarantees (PR2's lesson, composed under recursion)

Independently reproduced PR2's foreign-file-inside-orphan-media-dir
protection under a THREE-level nested source path (docs/reports/deep/
report.docx), including planting a foreign file inside the media directory
the nested source's handler produced, then orphaning it. Result: the whole
media directory, the foreign file, AND the legitimate image all survive,
correctly refused with a cause naming the foreign file -- identical
behavior to the flat (non-nested) case verified in PR2's own re-verification
pass. This confirms the apply-progress's claim that media cleanup needed
zero code changes to compose with recursion is genuinely true, not just
true for the happy path: _clean_orphan_media scans the FLAT sections/
ingested/ output directory, which recursion never touches (output identity
is content-hash only, never mirrors inbox folder structure), so every
PR2-era protection (shape check, content check, per-item error isolation)
composes automatically regardless of how deep the originating source lived.

## 5. New Port/Adapter Layering

- IngestArtifactWriter (domain/ports/ingest_artifact_writer.py): a plain
  typing.Protocol with one method (write_json), matching the existing
  port style in this codebase. No infrastructure import.
- FilesystemIngestArtifactWriter (infrastructure/ingest/
  filesystem_ingest_artifact_writer.py): genuinely atomic --
  tempfile.mkstemp(dir=path.parent, ...) creates the temp file on the SAME
  filesystem as the target (a true atomic os.replace, not a cross-device
  copy-then-delete), and a BaseException handler unlinks the temp file and
  re-raises on any failure (confirmed via the existing
  test_write_json_cleans_up_temp_file_when_serialization_fails test, which
  I re-ran). Deterministic: json.dumps(..., sort_keys=True, indent=2), no
  timestamps -- confirmed via test_write_json_creates_file_with_sorted_
  keys_and_no_timestamp.
- Wiring: confirmed via diff that cli/_shared.py's Deps.__init__ is the
  ONLY place FilesystemIngestArtifactWriter is imported or constructed --
  no other file references the infrastructure adapter directly, preserving
  the cli -> application -> domain dependency direction.
- IngestService's fallback _InlineJsonWriter (used only when no writer is
  injected) is explicitly documented as NOT atomic and exists solely so the
  dozens of pre-existing IngestService(detector, handlers) constructor
  calls across the test suite keep working -- a reasonable, narrowly-scoped
  compromise that does not leak into production (the real adapter is always
  wired in cli/_shared.py).

## 6. Report-Shape Consumer Sweep (final, across PR2+PR3)

Independently swept src/ for every consumer of the ingest report shape,
beyond what apply-progress already claims to have checked:

- src/docs/application/pipeline.py, stage_ingest: reads report["files"],
  report["processed"], and (since PR2's SUGGESTION-2 fix)
  report["media_cleanup"] -- never report["ignored"]. Confirmed the new
  "ignored" key is additive-only; stage_ingest's error-counting
  (f.get("status") == "error") correctly ignores empty_dir marker entries
  too (their status is "empty_dir", never "error").
- src/docs/application/collection.py: still reads an unrelated
  evidence_sources config block, confirmed unrelated (re-verified, same
  finding as PR2's review).
- No other src/ file references report["files"]/["processed"]/["ignored"]/
  ["media_cleanup"] or _detection.json/_source-manifest.json by literal
  path.
- Test-side: the two pre-existing exact-dict-equality tests
  (test_ingest_service.py, test_ingest_determinism.py) were updated in this
  batch to include the new "ignored": [] field alongside PR2's
  "media_cleanup" -- confirmed both still pass. No other exact-equality
  assertion against the full report was found.
- No spec/doc example presenting a literal _detection.json shape was found
  that would now be stale (same conclusion as the PR2 sweep).
- Verdict: the consumer sweep is genuinely complete; nothing missed.

## 7. Self-Referential Artifacts in `ignored` -- Honesty Judgment

See WARNING-1 above for the full analysis. Summary judgment: the report
stays HONEST (nothing is hidden or silently dropped -- both self-written
artifact files ARE reported, matching the "never silent" design principle
that governs every other exclusion in this front) but is not MAXIMALLY
clear, since the reason field cannot currently distinguish "this is our own
bookkeeping" from "this is a real exclusion a user might care about." An
agent reading only the report data (without independent knowledge that this
harness writes files literally named _detection.json/_source-manifest.json)
could not mechanically rule out that a real file was excluded, though the
literal filenames themselves are a strong hint. This is judged a narrow,
non-blocking clarity gap (WARNING, not CRITICAL) -- no data is ever lost or
misrepresented, only under-labeled.

## SUGGESTION-1 -- The inbox/assets/ top-level-only exclusion boundary has no pinning test

The implementation correctly excludes only a LITERAL top-level
inbox/assets/ subtree (matching design.md's consistent wording throughout
Decisions 2, 6, and 8), not any directory named "assets" at any depth --
independently confirmed via reproduction (a nested docs/assets/cover.png is
walked normally, not excluded). This is correct, intentional behavior, but
only the POSITIVE case (top-level assets/ IS excluded) is pinned by an
existing test; the boundary itself (nested assets/ is NOT excluded) is
untested. Recommend a small pinning test asserting a nested assets/ folder
is walked normally, so a future contributor cannot accidentally widen the
exclusion to match any "assets"-named directory without a test forcing a
conscious decision.

## SUGGESTION-2 -- Case-sensitive sort ordering is correct and documented, worth a one-line reader-facing note

Confirmed intentional (design.md Decision 2 explicitly says "case-sensitive"
POSIX sort, to avoid locale-dependent collation drift between Windows and
Linux) and independently reproduced (an uppercase-leading filename sorts
before an all-lowercase one, which could surprise a human skimming
_detection.json expecting conventional alphabetical order). No code change
needed -- purely a suggestion that the artifact map or _detection.json's
own module docstring could carry a one-line note explaining why entries
are NOT in the alphabetical order a human might expect, to save a future
reader from mistaking it for a bug.

## Spec Traceability

Confirmed each cited spec scenario under document-ingest's "Recursive Inbox
Scan with Provenance" and "Detection Report Run-vs-Prior Semantics"
requirements is genuinely satisfied by a real, passing test, not just
cited: "Nested subfolder file is detected with provenance" (7.1),
"Unsupported nested file is reported, not silent" / "Empty subfolder
produces no error" (7.2), "Batch sibling marked as converted-this-run" /
"Prior-run file marked as already-present" (7.5) -- all three requirement
groups' scenarios map directly onto real test assertions in
test_ingest_recursive.py, independently re-run and confirmed passing.

## Slice Discipline

Confirmed via diff-stat and a targeted diff check for every Front D-G file
path (domain/source_role.py, domain/near_duplicate.py,
domain/figure_catalog.py, domain/template_validation.py,
cli/commands/template_app.py): zero matches, zero diff. Only
application/ingest.py, cli/_shared.py (wiring only), the new port+adapter
pair, and their tests were touched. Phase 7's 9 tasks (7.1-7.9) map cleanly
onto real, verified code and tests. Slice discipline is intact.

## Independent Re-run Evidence (this pass)

- Full suite run twice independently: 988 passed, 0 failed, 7 skipped both
  times, byte-identical counts. Matches the claimed count exactly.
- ruff check: 15 errors on this branch. Compared against CURRENT main
  (post-PR2-merge, commit 7fbf044 tree) via a disposable git worktree
  (added and removed cleanly, never touching the live working tree) --
  also 15 errors, identical file:line violation set. 0 net new.
- mypy on the three genuinely new/modified files (ingest.py,
  ingest_artifact_writer.py, filesystem_ingest_artifact_writer.py): no
  issues. mypy on cli/_shared.py surfaces only transitive import-resolution
  errors in unrelated infrastructure files -- independently confirmed
  identical on main via the same disposable worktree, so these are
  pre-existing, not introduced by this batch.
- Isolated run of the recursive-ingest, media-cleanup, artifact-writer,
  ingest-service, and ingest-determinism suites (40 tests): all pass.
- Independently, empirically reproduced (not just read from the diff or
  trusted from existing tests): per-directory JVM batching with a
  realistic three-directory tree using a handler mirroring the real
  adapter's exact caching structure; the foreign-file-inside-orphan-dir
  protection composing correctly under three-level nesting; the
  self-referential ignored-list phenomenon; a nested (non-root) assets/
  folder being walked, not excluded; accented-filename and case-sensitive
  ordering behavior.
- No checkout-main-onto-live-tree mistake was made during this review; all
  main-baseline comparisons used a disposable git worktree add/remove.

## Issues Summary

| Severity | Count | Items |
|----------|-------|-------|
| CRITICAL | 0 | none |
| WARNING | 1 | self-referential harness artifacts share a generic ignored reason with genuine user exclusions |
| SUGGESTION | 2 | missing pinning test for the nested-assets-not-excluded boundary; case-sensitive ordering worth a reader-facing note |

## Verdict

ready-for-pr -- zero correctness defects found across eight adversarial
probe areas, all independently reproduced rather than trusted from the
diff or existing tests. The single WARNING is a report-clarity gap with no
data-loss or correctness impact (the report is always honest, just not
maximally self-explanatory to a consumer without out-of-band knowledge of
this harness's own artifact filenames); both SUGGESTIONs are pinning-test
and documentation nits for already-correct, already-intentional behavior.
None of these block merge; all are safe to defer to a follow-up hardening
task if the team prefers not to touch this branch again before shipping.
