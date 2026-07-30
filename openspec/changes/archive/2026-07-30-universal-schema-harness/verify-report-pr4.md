# Verify Report -- PR4 (Fronts D+E: source-role classification + near-duplicate detection)

Change: universal-schema-harness | Branch: feat/usch-d-roles-duplicates
Base: main @ 74268ef (merge of PR3, feat/usch-c-recursive-ingest)
Scope: Phases 8-9 (13 tasks, both front:roles-duplicates), plus 3 folded
PR3 verify follow-ups. Front F (Phase 10, verbatim assets + figure
catalog) and Front G (Phase 11-12) intentionally not implemented -- not
evaluated here except for slice-discipline leakage.
Reviewer: sdd-verify (fresh-context adversarial review, fourth target in
this change)

## Executive Summary

PR4 is mechanically solid (1022/1022 tests pass twice, ruff 15 matches
current main exactly, mypy clean) and the queue/reversal confirmation
mechanics are genuinely well-built -- independently verified across
MULTIPLE re-scans, not just one round-trip. But adversarial probing of the
near-duplicate detector surfaced 1 CRITICAL finding: the detector's text
normalization does not strip accents, and an empirical reproduction shows
this causes it to MISS the exact real-world scenario this feature was
built for (an accented curated version vs an unaccented/differently-
accented PDF-extracted version of the SAME Spanish-language document) --
jaccard drops to 0.12, far below the 0.85 threshold, so no duplicate is
ever recorded. The existing "real GUIA case" acceptance test uses
byte-IDENTICAL text for both fidelity variants, which trivially passes and
masks this gap entirely. 3 WARNINGs and 3 SUGGESTIONs cover secondary
normalization gaps, lexicon coverage gaps for this repo's own real folder
names, and a couple of low-severity edge-case oddities. Verdict:
needs-fixes -- the CRITICAL finding should be resolved (accent
normalization added to the shingle pipeline, with a realistic
accent-divergent test) before this front is considered done.

## CRITICAL-1 -- Near-duplicate detector has no accent normalization, silently missing its own flagship real-world scenario

- Where: src/docs/domain/near_duplicate.py, _shingles -- calls
  clean_markdown_text(text).lower() only. clean_markdown_text
  (src/docs/domain/markdown_text.py) strips bold/italic/code markers and
  collapses whitespace, but does NOT strip diacritics. An accent-stripping
  utility (_ACCENT_TRANSLATION, str.maketrans mapping accented Spanish
  vowels/enye to their bare form) already exists in the SAME module, used
  by a different function, but is never applied here.
- Independently reproduced: built two representative Spanish-language
  texts describing the same content, one with correct accents (as a
  hand-curated markdown file would have) and one without (as an OCR/PDF
  extraction plausibly would produce -- a well-known category of
  extraction artifact for accented Latin-script text). Jaccard score:
  0.12, nowhere near the 0.85 threshold. find_duplicates([...]) on this
  pair returns an EMPTY list -- no duplicate recorded at all, silently.
- This is not a hypothetical corner case: design.md's Decision 5 and the
  proposal both cite "a PDF-extracted copy and a native DOCX/curated copy"
  of the SAME document as the exemplar motivating scenario for this
  entire feature, and this repo's own real-world reference material is
  Spanish-language content laden with accents ("GUÍA", "estadía",
  "elaboración"). If a real extraction pipeline diverges from the curated
  original by so much as accent handling, this detector currently cannot
  catch it.
- The existing acceptance test that specifically claims to cover this
  scenario -- test_realistic_drop_shape_roles_and_near_duplicate_all_
  recorded_nothing_silent in tests/integration/test_ingest_roles_
  duplicates.py, whose own docstring says "extracted/GUIA-Estadia.md vs
  guides/GUIA-Estadia.pdf -- same guide, MD is the curated higher-fidelity
  copy" -- writes the exact SAME guide_text string verbatim to BOTH files
  (byte-identical content, not merely near-identical). This trivially
  produces jaccard=1.0 regardless of any normalization gap, giving false
  confidence that the "real GUIA case" is covered when the realistic
  failure mode (accent divergence between fidelity variants) is never
  actually exercised. Every other fidelity-ranking test in
  test_near_duplicate.py has the same pattern: text=text applied verbatim
  to both variants, never independently authored near-identical text with
  a realistic OCR-style divergence.
- Impact: not data loss (nothing is deleted; both the curated and the
  extracted copy simply stay independently "kept" and active, since no
  duplicate decision is ever recorded), but it defeats the feature's own
  stated purpose for its primary use case -- a genuine duplicate goes
  completely undetected, silently, with no error or gap reported anywhere.
- Fix: apply the existing _ACCENT_TRANSLATION (or an equivalent
  normalization step) inside _shingles before building shingles, and add
  at least one test using independently-authored, realistically
  accent-divergent text for the same underlying content (not the same
  string reused verbatim) to prove the fix actually closes the gap this
  finding demonstrates.

## 1. Classifier Determinism + Honesty

Confirmed pure-function determinism (classify(x) == classify(x) always,
zero I/O, zero randomness) via the existing test plus independent
reproduction. Adversarially probed beyond the existing suite:

- Ambiguous folder ("docs/report.md"): correctly resolves to unknown/low,
  no signals -- matches "Ambiguous source is queued, not defaulted."
- Files with no signals at all ("top-level-file.md"): unknown/low, as
  expected.
- Conflicting signals, UNEQUAL weight ("ejemplos/manual-x.md",
  "manual/ejemplo-anexo.md"): the stronger folder-level signal correctly
  wins over a weaker filename-only signal on the OTHER role -- not treated
  as ambiguous, matching the documented "folder priority" design intent
  and the existing test_stronger_signal_for_one_role_wins test.
- Conflicting signals, EQUAL weight ("normativa/ejemplo/foo.md", two
  folder-level hits for two different roles): correctly resolves to
  unknown/low -- genuinely ambiguous, never an arbitrary pick.
- Confidence values are bounded to exactly three buckets (high/medium/low)
  and deterministically ordered by score threshold (>=0.5 high, else
  medium when any signal exists, low only for the no-signal/tied case) --
  confirmed via direct reproduction across a dozen synthetic paths, no
  out-of-range or nondeterministic values observed.

### WARNING-1 -- The EXAMPLE and "extracted" concepts are not recognized by folder-lexicon matching for THIS repo's own real folder names

- Independently reproduced against the exact real-world folder names this
  repo's own fixtures already use: example_tesina/ (from
  reporte-estadia-tic.json's example_pdf path) and extracted/ (from the
  same fixture's extracted_dir path, and PR3's own realistic-drop
  acceptance test).
- example_tesina/RE-Ejemplo.pdf classifies correctly (example/medium), but
  ONLY via the FILENAME signal ("ejemplo" inside "RE-Ejemplo") -- the
  FOLDER itself ("example_tesina") produces zero signal, because the
  EXAMPLE lexicon lists "ejemplo"/"ejemplos"/"muestra"/"sample"/
  "reference"/"referencia"/"plantilla" but never the English "example"/
  "examples". A file in that same real folder with a generic filename
  (example_tesina/case-study.pdf, reproduced directly) gets ZERO signal --
  unknown/low -- despite living in a folder whose name clearly signals
  "this is example material" to a human.
- extracted/ is not in ANY of the three lexicons (normative/example/
  evidence). Every file in that folder gets zero folder-level signal;
  extracted/notes.md (reproduced directly) resolves to unknown/low.
  extracted/ is one of the three canonical real-world folder shapes this
  entire change's own explore.md, design.md, and PR3's acceptance test
  consistently reference -- in practice, essentially every file dropped
  there will need manual queue confirmation rather than being usefully
  auto-proposed, even though "extracted" content is plausibly always
  evidence/traceability material by construction.
- This matches design.md's literal lexicon lists faithfully (design.md
  itself never lists "example"/"extracted" as folder terms) -- not an
  implementation bug relative to design, but a real, evidence-backed
  product gap: the classifier's practical folder-level coverage for two
  of the three canonical real-world shapes this change's own fixtures use
  is effectively nil. Recommend a design-level follow-up to extend the
  lexicons (at minimum "example"/"examples" for the EXAMPLE role;
  consider whether "extracted" should map to EVIDENCE by default).

### SUGGESTION-1 -- EVIDENCE lexicon lists only the plural "anexos", not the singular "anexo"

Independently reproduced: "manual/ejemplo-anexo.md" does not get an
EVIDENCE filename hit for "anexo" (singular), only the folder-level
NORMATIVE hit wins in that specific case, so the gap was not visible
in that test, but a hypothetical "anexo/foto.png" (singular folder name)
would get zero EVIDENCE folder signal where "anexos/foto.png" (plural)
gets a high-confidence hit. A minor, low-priority lexicon completeness
gap -- real Spanish usage varies between singular and plural for this
term. Matches design.md's own literal lexicon list (not an implementation
deviation), same category as WARNING-1.

## 2. Queue as the ONLY Confirmation Interface (independently, empirically verified across multiple re-scans)

Read _read_prior_confirmed_roles/_build_manifest_sources/
_write_classification_queue directly: the ONLY way a non-null
confirmed_role can ever appear is by reading it back from an EXISTING
_classification-queue.json file on disk -- nothing in IngestService (or
anywhere else in src/) ever WRITES a non-null confirmed_role on its own
initiative; every write of that field is a pass-through of whatever was
just read. Confirmed no auto-confirmation path exists.

Independently reproduced THE critical case beyond a single round-trip:
simulated an external edit setting confirmed_role="evidence" on an
otherwise-unknown source, then ran ingest_inbox THREE additional times.
The confirmation survived every single re-scan (not just the immediate
next one) in both the queue file and the manifest. Also independently
verified draft vs strict gating: an unconfirmed source is admitted with a
PENDIENTE gap in draft mode and BLOCKED with a clear Spanish message in
strict mode; a source confirmed in an earlier scan stays unblocked in
strict mode even when a DIFFERENT, still-unconfirmed source in the same
scan is correctly blocked -- the gate is evaluated per-source, not
batch-wide.

## 3. Near-Duplicate Detector -- Additional Adversarial Findings

Beyond CRITICAL-1, independently probed:

### WARNING-2 -- Markdown structural markup (headings, list/blockquote markers) is not stripped, only bold/italic/code

_shingles calls clean_markdown_text, which strips **bold**/*italic*/
`code` markers and collapses whitespace, but NOT heading `#`, list `-`,
blockquote `>`, or table `|` markers -- that fuller stripping lives in a
DIFFERENT function in the same module (strip_frontmatter_and_markdown),
never called from near_duplicate.py. Independently reproduced: a plain
paragraph vs the same content with a "# Heading" prefix and **bold**
markup scored 0.92 (still above threshold in this specific case, because
only a few shingle windows near the `#`/markup were perturbed relative to
a longer body of matching text) -- but for shorter texts or texts with
heavier structural markup throughout (multiple headings/bullets), the
un-stripped `#`/`-`/`>` characters become their own spurious "words" in
the shingle windows, which would NOT appear in a comparably-formatted-
differently variant, likely dragging genuinely-similar documents below
threshold. Same root cause and same fix category as CRITICAL-1 (the
existing, more thorough markdown-stripping utility in this same file is
simply not being reused here) -- worth fixing together.

### WARNING-3 -- Documents shorter than 5 words can only ever be flagged as EXACT duplicates, never "near" duplicates

Independently reproduced: two 3-word/4-word documents differing by
exactly one added word scored jaccard=0.0 (not flagged), while two
IDENTICAL short documents scored 1.0. Because _shingles collapses any
text under 5 words into a SINGLE whole-text "shingle" (a tuple of however
many words there are), two short documents either match that single tuple
exactly (jaccard=1.0) or don't overlap at all (jaccard=0.0) -- there is no
graduated "near" match possible below the 5-word threshold. This is a
reasonable, safe default (it can never FALSELY flag two different short
snippets as duplicates), but it does mean the detector has zero fuzzy-
matching value for genuinely near-duplicate short files (e.g. a one-line
section summary edited slightly). Worth a one-line docstring note; not
independently blocking, but compounds with CRITICAL-1/WARNING-2's
normalization gaps for short, heavily-formatted, or accent-bearing files.

### SUGGESTION-2 -- Two empty documents are treated as 100% duplicates of each other

Independently reproduced: _jaccard(empty_set, empty_set) explicitly
returns 1.0 (the "not a and not b" branch), so two genuinely empty
ingested outputs (e.g. two unrelated failed/blank conversions) get
flagged as near-duplicates of each other with the reason string
"near-duplicate content (jaccard=1.0)", and one is marked superseded via
the ordinary fidelity/path tie-break -- even though there is no real
"content" similarity to speak of. Not a data-loss risk (nothing is
deleted, and the decision is auditable/reversible like any other), but a
slightly misleading edge case worth a one-line guard (e.g. treat two
empty documents as NOT comparable, skip the pair) or at least a code
comment acknowledging the deliberate choice.

### SUGGESTION-3 -- No corpus-size guard on the O(n^2) pairwise comparison

find_duplicates is a straightforward double loop over every pair of
input documents -- no chunking, blocking, or size-based short-circuit.
This is a DELIBERATE, documented design choice (design.md's Decision 5
explicitly rejects simhash/MinHash "at this corpus size exact Jaccard
over shingles is cheap and needs zero seeds"), not an oversight, so this
is not a defect -- but there is currently no comment or guard marking
WHERE that assumption would start to break down (e.g. a very large
inbox drop with hundreds of files), which could cause silent slowness
rather than a clear signal that a future front should revisit the
algorithm. Low priority, informational.

## 4. Fidelity Preference + Reversibility (independently verified across multiple re-scans)

Confirmed _rank_pair's fidelity order (md=0 > docx/odt=1 > pdf=2 > txt=3,
unrecognized kind = lowest) and POSIX-path tie-break via the existing
tests, and independently re-derived the ranking is order-independent
(find_duplicates([a,b]) == find_duplicates([b,a]) in kept/superseded
terms).

Reversibility, independently reproduced beyond a single round-trip:
ingested two byte-identical-content sources (curated.md, extracted.pdf),
confirmed the manifest records kept=curated.md/superseded=extracted.pdf
with jaccard+reason, then manually reversed the entry in
_source-manifest.json and re-ran ingest_inbox TWICE more. The reversal
held across both subsequent re-scans -- not a one-shot artifact. The
manifest duplicate record (kept, superseded, jaccard, reason) is
sufficient information for a human/agent to understand and undo the
preference, matching "auditable, reversible" (spec: "Duplicate decision
is reversible").

The losing (superseded) file's ingested OUTPUT is KEPT on disk, never
deleted -- independently confirmed by listing sections/ingested/ after a
duplicate decision: both the kept and superseded outputs remain as real
files. Only the manifest's `duplicates` list marks one as suppressed;
nothing is destroyed, matching design.md Decision 5's "nothing is removed
from disk, only their downstream use is suppressed" principle exactly.

## 5. Wiring

- IngestArtifactWriter (the same atomic port introduced in PR3) is reused
  for the new classification queue write
  (self.writer.write_json(inbox_dir / _CLASSIFICATION_QUEUE_NAME,
  payload)) -- no new writer/port was introduced for this front, correctly
  reusing the existing atomic+deterministic seam.
- Layering: domain/source_role.py imports only the stdlib `re` module;
  domain/near_duplicate.py imports stdlib `dataclasses` plus
  domain/markdown_text.clean_markdown_text (another domain module) --
  confirmed via direct import inspection that BOTH classifiers are pure
  domain code, zero I/O, zero infrastructure imports.
- confirmed_role/role_status/duplicates/proposed_role are produced AND
  consumed ONLY by application/ingest.py itself (round-tripped through the
  queue/manifest files) -- confirmed via a src/-wide grep that no other
  file references any of these fields. This matches the apply-progress's
  own explicit, honest disclosure that no cross-service consumer (e.g.
  excluding `evidence`-role sources from normative checks) exists yet to
  wire this data into -- correctly deferred, not silently missing.

## 6. Slice Discipline (including the Front-lettering dispute)

Confirmed via diff-stat and a targeted diff check for every Front F/G file
path (domain/figure_catalog.py, domain/template_validation.py,
cli/commands/template_app.py, domain/ports/image_metadata_port.py): zero
matches, zero diff. Only application/ingest.py, the two new domain
classifier files, and their tests were touched.

The apply-progress's slice-discipline defense (that the orchestrator's
mid-batch mention of "Front E (assets/figures)" was a factual mislabeling,
and that Phase 8+9 together are the correct front:roles-duplicates scope)
was independently re-verified against design.md's own "Suggested slicing
sketch" table: Front D = source-role classification (Decision 4), Front E
= near-duplicates (Decision 5), Front F = verbatim assets + figure catalog
(Decision 6) -- a DIFFERENT, later decision entirely. tasks.md itself tags
BOTH Phase 8 and Phase 9 with the identical [front:roles-duplicates] label.
This matches this reviewer's own independent reading of design.md from
earlier passes in this change. The apply agent's call to proceed on this
artifact evidence rather than the paraphrased mid-batch instruction was
correct.

## 7. Spec Traceability + Acceptance Test Meaningfulness

Confirmed each cited spec scenario under document-ingest's "Source-Role
Classification" and "Near-Duplicate Detection" requirements maps to a
real, passing test: "Deterministic signal classifies unambiguously" (8.1),
"Ambiguous source is queued, not defaulted" (8.2), "Confirmed role
recorded and enforced" (8.6), "Higher-fidelity duplicate is kept" (9.1),
"Distinct sources are not falsely merged" (9.2), "Duplicate decision is
reversible" (9.4) -- all independently re-run and confirmed passing.

Acceptance test meaningfulness, independently checked by construction (not
by mutating the test): the role-classification half of
test_realistic_drop_shape_roles_and_near_duplicate_all_recorded_nothing_
silent WOULD fail if a role came out wrong (it asserts exact
proposed_role/confidence values keyed to specific real folder names, not
just "some role was assigned"). The near-duplicate half of that SAME test,
however, would NOT fail if accent (or other realistic OCR-style)
divergence caused the duplicate to go undetected -- see CRITICAL-1: the
test's own fixture text is byte-identical between the two variants, so it
cannot distinguish "the detector genuinely works" from "the detector only
works when the input happens to be identical," which is exactly the gap
this review demonstrates is real.

## Independent Re-run Evidence (this pass)

- Full suite run twice independently: 1022 passed, 0 failed, 7 skipped
  both times, byte-identical counts. Matches the claimed count exactly.
- ruff check: 15 errors on this branch. Compared against CURRENT main
  (post-PR3-merge, commit 74268ef tree) via a disposable git worktree
  (added and removed cleanly, never touching the live working tree) --
  also 15 errors, identical file:line violation set. 0 net new.
- mypy on the three touched/new files (ingest.py, source_role.py,
  near_duplicate.py): no issues.
- Independently, empirically reproduced (not just read from the diff or
  trusted from existing tests): a dozen adversarial classifier paths
  (ambiguous folders, equal/unequal-weight signal conflicts, this repo's
  own real folder names); accent-divergent near-duplicate text (the
  CRITICAL finding); markdown-structure-divergent text; short-document and
  empty-document edge cases; threshold-boundary determinism across six
  perturbation levels; queue confirmation surviving three consecutive
  re-scans; near-duplicate manual reversal surviving three consecutive
  re-scans; confirmation that superseded outputs are never deleted from
  disk.
- No checkout-main-onto-live-tree mistake was made during this review; all
  main-baseline comparisons used a disposable git worktree add/remove.

## Issues Summary

| Severity | Count | Items |
|----------|-------|-------|
| CRITICAL | 1 | near-duplicate detector has no accent normalization, silently misses its own flagship real-world scenario |
| WARNING | 3 | folder-lexicon coverage gap for this repo's own real "example_tesina/"/"extracted/" folder names; near-duplicate detector doesn't strip markdown structural markup; short documents can only ever be exact-matched, never near-matched |
| SUGGESTION | 3 | singular "anexo" missing from EVIDENCE lexicon; two empty documents flagged as 100% duplicates of each other; no corpus-size guard/comment on the O(n^2) pairwise comparison |

## Verdict

needs-fixes -- CRITICAL-1 should be resolved (accent normalization added
to the near-duplicate shingle pipeline, plus a realistic accent-divergent
regression test) before this front is considered done, since it silently
defeats the feature's own stated purpose for the exact real-world scenario
that motivated building it. The queue-confirmation and duplicate-reversal
mechanics are genuinely solid and independently verified across multiple
re-scans -- this is not a broad implementation-quality problem, it is a
specific, well-evidenced, and straightforwardly fixable normalization gap
(the fix material -- accent stripping -- already exists elsewhere in the
same file). WARNING-2 (markdown structural markup) shares the same root
cause and is worth fixing in the same pass. WARNING-1 and the SUGGESTIONs
are lower-priority, independently deferrable hardening items.

---

# Re-verification (fix batch: 7c1a32e, 74211a0, 3fe232f, 2cdcf84)

Second fresh-context pass on PR4, targeted at closing the findings above.
No code was changed by this review; only this report was appended to
(working-tree only, not committed by this agent).

## Per-finding status

| Finding | Status | Evidence |
|---------|--------|----------|
| CRITICAL-1 (no accent normalization) | FIXED | Re-ran the exact original reproduction (accented curated vs unaccented extracted Spanish text) -- now scores jaccard=1.0 and is correctly flagged as a duplicate. Fix reuses markdown_text._ACCENT_TRANSLATION directly (confirmed via import + call site inspection), no duplicated normalization logic. |
| The test mask (acceptance test used byte-identical text) | FIXED, and independently PROVEN non-vacuous | See dedicated section below -- built a disposable worktree, neutered the normalization fix in that isolated copy only, and confirmed the rewritten acceptance test AND the two new unit tests go genuinely red. |
| WARNING-1 (lexicon gaps for example_tesina/, extracted/) | FIXED | Re-ran the exact original real-folder-name reproductions -- extracted/notes.md now resolves evidence/high; example_tesina/case-study.pdf (generic filename) now resolves example/high via a folder-level hit; example_tesina/RE-Ejemplo.pdf now gets a combined folder+filename signal (confidence raised from medium to high). |
| SUGGESTION-1 (singular "anexo" missing) | FIXED | anexo/foto.png now resolves evidence/high; plural anexos/ re-checked, no regression. |
| WARNING-2 (markdown structural markup not stripped) | FIXED | Re-ran the exact original probe (plain vs heading+bold-formatted text) -- now scores jaccard=1.0 (was 0.92, already-passing but now fully normalized), via strip_frontmatter_and_markdown reused ahead of clean_markdown_text. |
| WARNING-3 (short documents can only be exact-or-disjoint) | CONFIRMED INTENTIONALLY UNCHANGED | Re-ran the exact original short-document reproduction -- behavior is identical (near-identical 3-vs-4-word docs still score 0.0). This was the correct disposition: the finding was that this is a safe, deliberate limitation, not a defect, and it is now explicitly documented in a code comment and pinned by a dedicated test (test_short_documents_below_shingle_size_can_only_be_exact_or_disjoint). |
| SUGGESTION-2 (empty docs flagged 100% duplicate) | FIXED | Re-ran the exact original empty-document reproduction -- two empty documents now score jaccard=0.0 and find_duplicates returns an empty list (was 1.0 / flagged before). Fixed at two levels: _jaccard's not-a-and-not-b branch now returns 0.0, AND find_duplicates filters zero-shingle documents out of the pairwise pass entirely before any comparison (defense in depth, confirmed via code read). |
| SUGGESTION-3 (no O(n^2) comment) | FIXED | find_duplicates's docstring now explicitly documents the deliberate O(n^2) choice, citing design.md Decision 5's own simhash/MinHash rejection, and flags where that assumption would need revisiting. |

## Non-Vacuous Test Proof (specifically requested): neutering the fix in a disposable worktree

To confirm the rewritten acceptance test and the two new unit tests are
genuine regression tests and not merely passing by construction, this
review:

1. Created a disposable git worktree at the current HEAD (never the live
   working tree).
2. Inside that isolated copy ONLY, edited _normalize_for_shingling to
   revert to the pre-fix behavior (clean_markdown_text(text).lower()
   alone, skipping both the accent-fold and the markdown-structure strip).
3. Ran the affected test files inside that isolated copy.

Result: exactly the tests tied to this fix batch went red, nothing else --
test_accent_and_markup_divergent_curated_vs_extracted_text_is_detected_
as_near_duplicate FAILED, test_markdown_structural_markup_divergence_does_
not_prevent_near_duplicate_detection FAILED, and
test_realistic_drop_shape_roles_and_near_duplicate_all_recorded_nothing_
silent FAILED (manifest["duplicates"] came back empty instead of length
1). The other 11 near_duplicate tests, including both new empty-document
and the short-document pinning tests, stayed GREEN under the same
neutering, confirming those fixes are independent of the accent/markdown
normalization step and were correctly not conflated with it. The
disposable worktree was removed immediately after (git worktree remove),
never touching the live branch.

This directly confirms: the rewritten acceptance test's two GUIA variants
are genuinely independently-derived (curated accented text vs a
test-local, production-independent unicodedata-based accent-stripped +
markdown-noised variant, per the diff) and the test CANNOT pass without
real normalization in production code -- it is not a mask, and it is not
vacuous.

## Accent-only-difference labeling sanity check (specifically requested)

Independently probed whether "two files differing ONLY in accents" being
newly recognized as near-duplicates is labeled sanely, not confusingly, as
"exact" vs "near": constructed a pair of texts identical except for every
accent mark, and a separate pair of genuinely byte-identical texts. Both
score jaccard=1.0 after normalization and both get the SAME reason string
shape ("near-duplicate content (jaccard=1.0)"). This is judged sane, not
misleading: the reason string has always used "near-duplicate" generically
regardless of whether the score is a perfect 1.0 or a partial match above
threshold (a byte-identical pair was ALREADY labeled this way before this
fix batch, e.g. in the pre-existing test_identical_text_is_flagged_a_near_
duplicate). The jaccard value itself (1.0) accurately and observably
reflects "identical after normalization" -- the manifest does not claim
the two source FILES were byte-identical, only that their extracted
CONTENT is a near-duplicate at the recorded score, which is accurate in
both cases. No new mislabeling risk was introduced by this fix.

## Confirmation-Persistence and Reversal -- Confirmed Not Weakened

Re-ran the full isolated suite covering queue confirmation and
near-duplicate reversal (tests/integration/test_ingest_roles_duplicates.py,
tests/unit/domain/test_near_duplicate.py, tests/unit/domain/
test_source_role.py -- 41 tests, all pass), including
test_confirmed_role_in_queue_round_trips_into_manifest_on_next_scan and
test_near_duplicate_decision_is_reversible_by_editing_the_manifest, both
unmodified by this fix batch and both still green. The fix batch touched
only near_duplicate.py's normalization internals and source_role.py's
lexicon constants -- neither the classification-queue read/write path nor
the manifest-override read/write path in application/ingest.py was
touched by this fix batch (confirmed via diff-stat: only near_duplicate.py,
source_role.py, and their own test files changed). No regression risk to
the confirmation/reversal mechanics this review verified across multiple
re-scans in the original pass.

## Independent Re-run Evidence (this pass)

- Full suite run twice independently: 1031 passed, 0 failed, 7 skipped
  both times, byte-identical counts. Matches the claimed count exactly.
- ruff check: 15 errors on this branch. Compared against CURRENT main via
  a disposable git worktree (added and removed cleanly, never touching the
  live working tree) -- also 15 errors, identical file:line violation set.
  0 net new.
- mypy on the three touched files (near_duplicate.py, source_role.py,
  ingest.py): no issues.
- Isolated run of all PR4-related suites (41 tests): all pass.
- Independently reproduced every original adversarial case against the
  fixed code (accent divergence, markdown-structure divergence, both real
  folder names, singular anexo, empty documents, short documents) --
  covered above per finding.
- Additionally, independently proved non-vacuousness by neutering the fix
  in a disposable worktree and confirming exactly the expected tests go
  red -- see dedicated section above.
- No checkout-main-onto-live-tree mistake was made during this review; all
  main-baseline comparisons and the neutering check used disposable git
  worktrees, added and removed cleanly.

## Re-verification Verdict

ready-for-pr -- all findings from the original pass (1 CRITICAL, 3
WARNING, 3 SUGGESTION) are genuinely, verifiably closed. The CRITICAL
finding's fix was independently proven non-vacuous by neutering it in a
disposable worktree and watching the exact expected tests go red -- this
is not a performative fix. The accent-only-difference labeling question
was checked and found sane. Confirmation-persistence and duplicate-
reversal mechanics are unmodified by this fix batch and remain fully
green. No new findings from this pass.
