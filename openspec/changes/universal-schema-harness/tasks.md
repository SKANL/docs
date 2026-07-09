# Tasks: Universal Schema Harness

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~2600-3200 total (7 fronts) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (A) -> PR 2 (B) -> PR 3 (C) -> PR 4 (D) -> PR 5 (E) -> PR 6 (F) -> PR 7 (G) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Front A: characterization + guard tests, policy de-hardcoding, `_valid_extra()` split, normative evacuation, `evidence.py`/`build-rules` first-use fixes | PR 1 | ~700-900 lines; the falsifiable acceptance gate (`documento-generico` clean, `reporte-estadia-tic` identical); base = tracker/main per chosen strategy |
| 2 | Front B: `doc new` creates `inbox/`+`inbox/assets/`, orphan `_media/` cleanup | PR 2 | ~150-250 lines; independent of A, depends only on existing workspace code; base = PR 1 branch (feature-branch-chain) or main (stacked) |
| 3 | Front C: recursive ingest walk, provenance, `batched` status, `IngestArtifactWriter` port+adapter | PR 3 | ~400-550 lines; depends on B (`inbox/` must exist); spine for D/E/F |
| 4 | Front D: source-role classifier + classification queue + manifest gating | PR 4 | ~250-350 lines; depends on C |
| 5 | Front E: near-duplicate detection (shingle/Jaccard) + fidelity ranking in manifest | PR 5 | ~250-350 lines; depends on C; independent of D |
| 6 | Front F: verbatim-asset routing, placement queue, `ImageMetadataPort` + figure catalog | PR 6 | ~350-450 lines; depends on C; independent of D/E |
| 7 | Front G: `template init`/`validate`, gap report, draft/strict wiring | PR 7 | ~350-450 lines; depends on A (shares `_check_missing_section_contracts` logic) |

If `feature-branch-chain` is chosen: PR 1 targets the tracker branch; PR 2 targets PR 1's branch; PR 3 targets PR 2's branch; PR 4/5/6 each target PR 3's branch (parallel siblings, rebase before merge to avoid cross-pollution); PR 7 targets PR 1's branch (only needs A). If `stacked-to-main`: each front merges to main independently in the same order, respecting the `B -> C -> {D,E,F}` and `A -> G` dependency edges.

---

## Phase 1: Characterization net (front A, step 1 — must be green before any rules.py edit)

- [x] 1.1 [front:policy-dehardcode] [spec: document-template "No hardcoded document-type literal in domain code"] Add `tests/unit/domain/test_rules_characterization.py`: snapshot current `review_rules(reporte_estadia_template, ...)` output and `review_section_text` output for a representative estadía section corpus (RED first — write against current code, confirm GREEN as baseline capture, not a behavior change).
- [x] 1.2 [front:policy-dehardcode] [spec: document-template "No hardcoded document-type literal"] Add `tests/unit/test_no_document_type_literal.py`: structural guard scanning `domain/rules.py` + `domain/normative.py` source text for banished literals (`"introduccion"`, `_EXPECTED_MARGIN_CM`/`2.5`, `"margins-2-5cm-non-cover"`, `"docs/extracted"`, `"rules_traceability_only"`, `"manual-estadia-tic"`, Spanish first-person/subjective lexicons). Expect this test to FAIL initially (literals still present) — it is the enforcement gate for tasks 2.x.

## Phase 2: `_valid_extra()` baseline split (front A, step 2)

- [x] 2.1 [front:policy-dehardcode] [spec: document-template "Optional-Block Absence Semantics"] In `tests/unit/domain/test_rules.py`, add `_generic_extra()` builder (no preliminaries/margins/extracted blocks) and `_estadia_extra()` builder (current `_valid_extra()` contents renamed, unchanged values).
- [x] 2.2 [front:policy-dehardcode] Re-target the ~15 tests currently depending on `_valid_extra()` to whichever of `_generic_extra()`/`_estadia_extra()` matches their intent; delete `_valid_extra()` once no test references it.
- [x] 2.3 [front:policy-dehardcode] [spec: document-template "Absent preliminaries/extracted-dir block skips the check"] Add new "stays silent when block absent" tests per check: `_check_extracted_dir_policy`, `_check_preliminaries_pagination`, `_check_margins_and_cover_policy` — each asserts no issue is raised when its block is absent, using `_generic_extra()`.

## Phase 3: Policy check conversions (front A, step 3)

- [x] 3.1 [front:policy-dehardcode] [spec: document-pipeline "APA gate respected"] In `domain/rules.py`, delete `_check_apa7_enabled` and its call site (rely on `review_apa7_text`'s existing `apa7.enabled` no-op gate). Run `_estadia_extra()` tests — must stay green (characterization proof).
- [x] 3.2 [front:policy-dehardcode] [spec: document-pipeline "Extracted-dir policy checked only when configured"] Rewrite `_check_extracted_dir_policy` in `domain/rules.py`: fire only if `paths.extracted_dir` set; validate policy value is internally consistent (drop hardcoded `"rules_traceability_only"` literal).
- [x] 3.3 [front:policy-dehardcode] [spec: document-pipeline "Extracted-dir policy checked only when configured"] Rewrite `_check_source_priority_excludes_extracted` in `domain/rules.py`: compare `source_priority` against the template's own `extracted_dir` value, not the literal `"docs/extracted"`.
- [x] 3.4 [front:policy-dehardcode] [spec: document-pipeline "Preliminaries checked only when declared"] Rewrite `_check_preliminaries_pagination` in `domain/rules.py`: fire only if `preliminaries` present; validate `body_pagination_start.section_id` references an existing `template.sections`/`structure` entry (not the literal `"introduccion"`); roman check only if the roman block is declared.
- [x] 3.5 [front:policy-dehardcode] [spec: document-pipeline "Margins checked for shape, not value"] Rewrite `_check_margins_and_cover_policy` in `domain/rules.py`: fire only if `format.page_margins_cm.non_cover` present; validate the four keys hold numeric cm values (delete `_EXPECTED_MARGIN_CM`); cover-policy check only if `cover_policy` declared.
- [x] 3.6 [front:policy-dehardcode] Delete `_check_margin_advisor_override_active` in `domain/rules.py` (couples to literal id `margins-2-5cm-non-cover`; the margin check above already validates the contract). Run `test_no_document_type_literal.py` — must now pass.
- [x] 3.7 [front:policy-dehardcode] Run `test_rules_characterization.py` — must byte-match the Phase 1 snapshot (no behavior drift for `reporte-estadia-tic`).

## Phase 4: Normative-defaults evacuation (front A, step 4)

- [x] 4.1 [front:policy-dehardcode] [spec: document-template "No hardcoded document-type literal"] In `domain/normative.py`, empty `EXCLUDED_FRONT_MATTER`, `FIRST_PERSON_PATTERNS`, `SUBJECTIVE_TERMS` module constants; make `resolve_normative_settings` defaults empty (keep `SECRET_PATTERNS` unchanged — language-neutral security default).
- [x] 4.2 [front:policy-dehardcode] Backfill the evacuated Spanish-thesis lexicons into the `reporte-estadia-tic.json` template fixture as explicit normative-config blocks, so runtime behavior stays byte-identical. (Already present verbatim in the fixture's `normative` block — verified equal to the former module constants field-by-field; no fixture edit needed.)
- [x] 4.3 [front:policy-dehardcode] Run `test_rules_characterization.py` (`review_section_text` snapshot) — must byte-match Phase 1. This is the backfill correctness proof.

## Phase 5: First-use bug fixes (front A, step 5 — unblocks `documento-generico`)

- [x] 5.1 [front:first-use-bugs] [spec: document-pipeline "Empty paths config does not crash build-rules"] Add failing test in `tests/integration/test_evidence_service.py`: `build-rules` on `documento-generico` (empty `paths`) must not raise `KeyError`.
- [x] 5.2 [front:first-use-bugs] In `application/evidence.py`, guard `manual_dir`/`extracted_dir` access with `.get()` (mirror `rules_hash` at line 121); skip absent dirs with a reported gap in the manifest instead of raising. Run 5.1 — must pass.
- [x] 5.3 [front:first-use-bugs] [spec: document-template "No hardcoded document-type literal" / evidence.py #7] Add failing unit test in `tests/unit/domain/test_evidence.py` asserting `build_manifest`'s `normative_source` comes from `normative.normative_source` (template-declared), not a hardcoded literal.
- [x] 5.4 [front:first-use-bugs] In `domain/evidence.py`, make `normative_source` a parameter sourced from the template, default `""`. Run 5.3 and `test_no_document_type_literal.py` — both must pass.
- [x] 5.5 [front:first-use-bugs] [spec: document-pipeline "New document workspace includes inbox/"] Add failing test in `tests/unit/application/test_documents.py`: new document workspace creation includes `inbox/`.
- [x] 5.6 [front:first-use-bugs] In `application/documents.py`, add `inbox/` (and `inbox/assets/` — shared with front F, created here since bootstrap owns `_SUBDIRS`) to `_SUBDIRS`. Run 5.5 and existing `test_documents.py` suite (subdirectory regression) — must pass.
- [x] 5.7 [front:first-use-bugs] Run full determinism suite ×2 (byte-identical outputs) as the Front A closeout gate.

---

## Apply Progress — PR1 batch (branch `feat/usch-a-policy-dehardcode`)

**Batch boundary**: Phases 1-5 (characterization net + Front A policy-dehardcode
+ Front A first-use bug fixes). Phase 6 (Front B, orphan `_media/` cleanup) is
explicitly OUT of scope for this batch — it belongs to PR2 per the Suggested
Work Units table (Unit 2).

**Status**: 22/22 tasks in Phases 1-5 complete (`[x]`), PLUS the fix-verify
round below. Ready for a second fresh-context review before push+PR.

**Commits** (work units, oldest to newest):
1. `73d5433` test(rules): add characterization net and no-literal guard for policy de-hardcoding (Phase 1)
2. `12fe5be` test(rules): split _valid_extra baseline into generic/estadia builders (Phase 2)
3. `86f29d0` refactor(rules): convert hardcoded policy checks to conditional/consistency form (Phase 3)
4. `8785c54` refactor(normative): evacuate Spanish-thesis lexicons from domain defaults (Phase 4)
5. `1228ac7` fix(evidence): guard absent paths and drop hardcoded normative_source (Phase 5.1-5.4)
6. `5cd34e5` feat(documents): create inbox/ and inbox/assets/ on document creation (Phase 5.5-5.6)
7. `77f7ecd` test(rules): add documento-generico falsifiable acceptance gate (extra, beyond numbered tasks — proves the proposal's success criterion end-to-end)
8. `c77bd4d` docs(tasks): check off Phase 1-5 tasks and record PR1 apply-progress

**Fix-verify round** (fresh-context `sdd-verify` returned needs-fixes; this
round resolves every finding, same branch, strict TDD throughout):
9. `d75ee83` fix(evidence): stop normative_source/pdf_and_extracted_use from silently regressing (CRITICAL-1 + WARNING-2)
10. `ff159ad` test(rules): close quote-style and bare-value bypass gaps in no-literal guard (WARNING-1)
11. `cef4b67` fix(rules): add missing silence test and reject bool margin values (SUGGESTION-1 + SUGGESTION-3)
12. `a93acd0` docs(planning): commit universal-schema-harness SDD audit trail (item 7 — proposal/explore/design/specs/state.yaml/verify-report-pr1.md)
13. (this commit) docs(tasks): record fix-verify round in apply-progress

WARNING-3 (spec.md wording) was resolved as an ADDITIVE clarification note
in `openspec/changes/universal-schema-harness/specs/document-pipeline/spec.md`
under the "Extracted-dir policy checked only when configured" scenario,
folded into commit `a93acd0` since it lives in the same previously-untracked
planning-artifact tree — no scenario text was replaced, only a clarifying
blockquote was added.

**Fix-verify findings and resolutions**:
- **CRITICAL-1** (normative_source silently regressed to `""` for the real
  `reporte-estadia-tic` fixture): backfilled `normative.normative_source:
  "docs/guides/manual-estadia-tic"` into the fixture (mirrors Decision 1d's
  lexicon backfill). Failing-test-first: a REAL-fixture-driven integration
  test in `tests/integration/test_evidence_service.py` plus a new
  characterization-net test in `test_rules_characterization.py` that snapshots
  `build_manifest`'s full `policy` block (closing the exact gap that let this
  regression slip through — the original net only covered
  `review_rules`/`review_section_text`).
- **WARNING-2** (`"pdf_and_extracted_use": "rules_traceability_only"`
  hardcoded in `domain/evidence.py`, outside the guard's scan scope): made it
  a `build_manifest` parameter sourced from the template's own
  `paths.extracted_dir_policy` (the same field `_check_extracted_dir_policy`
  already validates) — `documento-generico` (no `extracted_dir_policy`
  declared) now correctly gets `""`, not an invented value.
- **WARNING-1** (no-literal guard bypass gaps): banned `"introduccion"` and
  the margin value `2.5` as quote-agnostic bare substrings instead of a
  double-quoted literal / constant-name-only match; added synthetic-source
  tests (never touching production code) proving both bypasses are now caught.
- **WARNING-3** (spec.md wording vs. two-function split): additive
  clarification note added, planning artifact otherwise unchanged.
- **SUGGESTION-1**: added the missing `_check_source_priority_excludes_extracted`
  "stays silent when `paths.extracted_dir` absent" unit test, for symmetry
  with the other 3 conditional checks.
- **SUGGESTION-3**: `_check_margins_and_cover_policy` now explicitly rejects
  `bool` margin values (Python's `bool` subclasses `int`, so the prior
  `isinstance(x, (int, float))` silently accepted `True`/`False`).
- **SUGGESTION-2** (diff-size overage note): no action required per the
  verify report itself — informational only.

**Acceptance verification** (all confirmed, post-fix-batch):
- Full suite green twice in a row: 954 passed, 0 failed, 7 skipped (both runs
  byte-identical pass/fail counts — no flakes).
- `documento-generico` passes `review-rules`, `build-rules`, and `doctor`'s
  `rules_config` check with zero errors — integration-tested in
  `tests/integration/test_documento_generico_acceptance.py` (not manually).
- `reporte-estadia-tic` characterization snapshots
  (`tests/unit/domain/test_rules_characterization.py`, now including the
  `build_manifest` policy-block snapshot) stay green.
- Structural no-literal guard (`tests/unit/test_no_document_type_literal.py`)
  passes for both `domain/rules.py` and `domain/normative.py`, with the
  quote-style/bare-value bypass gaps closed and proven caught.
- `ruff check .`: 16 errors, unchanged from main's baseline (0 net new).
- `mypy src/docs/domain/rules.py src/docs/domain/normative.py
  src/docs/domain/evidence.py src/docs/application/evidence.py
  src/docs/application/documents.py`: no issues (main's pre-existing mypy
  errors live in unrelated files, untouched by this batch).

**Deviations from design worth flagging for `sdd-verify`**:
- `_check_preliminaries_pagination` changed signature from `(extra: dict)` to
  `(template: Template)` to access `template.sections` for the
  "references an existing section" consistency check (design only said
  "in `domain/rules.py`", not the exact signature).
- `_check_extracted_dir_policy`'s "internally consistent" language was
  implemented as "a non-empty string policy must be declared when
  `paths.extracted_dir` is set" (presence/shape check), not a value
  comparison — no other literal-free interpretation was available per the
  design's own principle table ("Conditional, not literal").
- Many `tests/unit/domain/test_rules.py` tests that asserted the OLD
  hardcoded-literal failure messages (e.g. "must be `rules_traceability_only`",
  "must be `preserve_template`", "must be 2.5cm", "must be `introduccion`")
  were rewritten (not just renamed) to test the NEW conditional/consistency
  behavior, since their original premise (comparing against a hardcoded
  literal) is exactly what this front removes. Each rewrite is called out
  with an inline comment referencing the relevant spec scenario.
- `_check_apa7_enabled` and `_check_margin_advisor_override_active` deletions
  removed their dedicated unit tests entirely (functions no longer exist);
  coverage of the resulting behavior (no issue forced) is folded into the
  renamed `review_rules`-level tests instead.

**Not started** (future batches): Phase 6 (Front B) onward — Fronts B-G per
the design's slicing sketch, PR2 through PR7. **UPDATE**: Phase 6 (Front B)
is now done — see the "Apply Progress — PR2 batch" section below.

## Phase 6: Front B — orphan `_media/` cleanup

- [x] 6.1 [front:first-use-bugs] [spec: document-ingest "Re-ingesting a source removes its stale media directory"] Add failing test in new `tests/unit/application/test_media_cleanup.py`: content-addressed `_media/` orphan (no current output references it) is removed.
- [x] 6.2 [front:first-use-bugs] [spec: document-ingest "Referenced media is never deleted"] Add failing test in the same file: a file under `_media/` not matching the content-addressed pattern is refused (left in place, reported in `_detection.json.ignored`).
- [x] 6.3 [front:first-use-bugs] Implement orphan cleanup step in `application/ingest.py` (runs during the ingest scan): remove only content-addressed orphans with no current reference; refuse and report anything else. Run 6.1-6.2 — must pass.
- [x] 6.4 [front:first-use-bugs] Run determinism suite ×2 for Front B closeout.

---

## Apply Progress — PR2 batch (branch `feat/usch-b-bootstrap-media`)

**Batch boundary**: Phase 6 only (Front B — orphan `_media/` cleanup), plus
one additional item folded in per the orchestrator's instruction: NEW-SUGGESTION-1
(`application/doctor.py`'s sibling hardcoded `extracted_dir_policy` literal,
recorded in `state.yaml`/`verify-report-pr1.md` as a PR1 follow-up, not in
PR1's own scope). Branched from `main` at merge commit `d7ad6b5` (PR #12,
the PR1 slice). Front C (Phase 7) onward is explicitly OUT of scope.

**Status**: 4/4 Phase 6 tasks complete (`[x]`), plus the NEW-SUGGESTION-1
follow-up. Ready for fresh-context review before push+PR.

**Commits** (work units, oldest to newest):
1. `c7cd40e` feat(ingest): clean up orphaned content-addressed _media/ directories (Phase 6.1-6.4)
2. `4e6d0bf` fix(doctor): de-hardcode extracted_dir_policy comparison in run_doctor (NEW-SUGGESTION-1)

**Implementation notes**:
- Media-dir identity: `PandocIngestAdapter` already names media directories
  `<stem>-<kind>-<sha8>_media` (mirrors the paired `.md` output's own
  `<stem>-<kind>-<sha8>.md` identity from `domain/ingest_naming.py`).
  `_clean_orphan_media` matches that exact shape via regex
  (`^(.+-[0-9a-f]{8})_media$`) rather than re-hashing directory contents —
  cheap, deterministic, and the shape alone is sufficient because only this
  harness's own adapter could have produced it.
- Orphan = matches the content-addressed shape AND its paired `.md` sibling
  no longer exists in `sections/ingested/`. Foreign = does not match the
  shape at all (left in place, unconditionally refused, never descended
  into or partially touched).
- New `report["media_cleanup"] = {"removed": [...], "refused": [...]}`
  field, always present (even empty) on every `ingest_inbox` call — required
  updating 2 PRE-EXISTING tests that asserted `report == {"processed": 0,
  "files": []}` by exact equality
  (`tests/unit/application/test_ingest_service.py`,
  `tests/integration/test_ingest_determinism.py`); both now assert the
  additive field's empty-default shape too. This is the "every output the
  touched code produces" lesson from PR1's CRITICAL-1 applied proactively —
  the new field's presence was captured in a regression test immediately,
  not discovered later by a reviewer.
- NEW-SUGGESTION-1 fix mirrors `_check_extracted_dir_policy` exactly (a
  policy must be declared as a non-empty string when `extracted_dir` is set;
  never a hardcoded expected value). The no-literal structural guard's scan
  scope was deliberately NOT extended to `application/doctor.py` — documented
  inline in `tests/unit/test_no_document_type_literal.py`'s module docstring:
  Decision 10.2 scopes the guard to `domain/rules.py` + `domain/normative.py`
  specifically, and `application/doctor.py` is a different architectural
  layer, matching the disposition WARNING-2 already established for
  `domain/evidence.py`'s `pdf_and_extracted_use`. Widening the guard's file
  list is a separately-reviewable decision, not something to fold in
  silently alongside this bugfix.

**Incident note (process, not code)**: while comparing ruff baselines against
`main`, `git checkout main -- .` was run directly against the live working
tree (the same mistake the PR1 verify report's reviewer made and documented).
`git stash` had been run immediately before it, so no work was lost. Recovered
via `git checkout HEAD -- .` followed by `git stash pop`; verified via
`git diff --stat` (matched the pre-incident diff exactly) and a full
`pytest` run (961 passed) before continuing. All subsequent `main`-baseline
ruff comparisons were done via a disposable `git worktree` instead. No
commits, pushes, or `state.yaml` changes were made during the incident or its
recovery.

**Acceptance verification** (all confirmed):
- Full suite green twice in a row: 961 passed, 0 failed, 7 skipped (both runs
  byte-identical pass/fail counts — no flakes).
- `ruff check .`: 16 errors on `main` (re-checked via disposable worktree,
  never by mutating the working tree after the incident above) and 16 on
  this branch — 0 net new.
- `mypy src/docs/application/doctor.py src/docs/application/ingest.py`: no
  issues.

**Fix-verify round** (fresh-context `sdd-verify` returned needs-fixes — 0
CRITICAL, 4 WARNING, 2 SUGGESTION, full report:
`openspec/changes/universal-schema-harness/verify-report-pr2.md`; this round
resolves every finding, same branch, strict TDD throughout):
3. `0170726` fix(ingest): refuse orphan media dirs with unexpected content, isolate per-item errors (WARNING-1 + SUGGESTION-1)
4. `a8d4091` test(doctor): add real reporte-estadia-tic/documento-generico fixture regression (WARNING-3)
5. `b5c536c` feat(pipeline): surface media cleanup activity in ingest stage detail (SUGGESTION-2)
6. `fc739b4` docs(planning): clarify refused-field naming and record guard-scope follow-up (WARNING-2 + WARNING-4)
7. (this commit) docs(tasks): record PR2 fix-verify round in apply-progress

**Fix-verify findings and resolutions**:
- **WARNING-1** (foreign file inside a shape-matching orphan dir destroyed
  along with it): hardened `_clean_orphan_media` to inspect every file
  (recursively) against an allowlist of expected pandoc-media extensions
  before deleting; any unrecognized file refuses the WHOLE directory
  (never partial-delete), reported with a `cause`. Failing-test-first
  reproduced the verifier's exact scenario (`image1.png` + `my_personal_
  notes.txt` inside `readme-md-a1b2c3d4_media`, no paired `.md`) — the
  directory and BOTH files now survive, reported under `refused`.
- **SUGGESTION-1** (no per-item exception isolation in the cleanup loop):
  wrapped each media-dir's processing in a `try`/`except OSError`, mirroring
  `_ingest_one_safely`'s existing convention a few lines away. Tested via a
  monkeypatched `shutil.rmtree` raising for one directory — that directory
  is reported refused with the OS error as its cause, and the OTHER
  directory in the same scan still gets cleaned up normally (loop
  continues, `ingest_inbox` never raises).
- **`report["media_cleanup"]["refused"]` shape change**: from a bare list of
  directory names to a list of `{"path": ..., "cause": ...}` entries, to
  carry the new refusal reasons WARNING-1/SUGGESTION-1 introduced. Updated
  the one existing test asserting the old bare-string shape
  (`test_foreign_non_content_addressed_media_dir_is_refused_not_deleted`).
- **WARNING-2** (field naming deviates from task/design's literal
  `_detection.json.ignored` wording, undisclosed): kept the `refused` name
  (its `{path, cause}` shape is now load-bearing for WARNING-1/SUGGESTION-1
  and would not fit a bare `ignored` list cleanly); added an ADDITIVE
  clarification blockquote to design.md's Decision 8 stating the deviation
  and its reasoning explicitly (Front C is expected to introduce its own
  shared top-level `ignored` field later; pre-empting that now would create
  churn). This paragraph itself IS the disclosure the verifier asked for.
- **WARNING-3** (doctor.py de-hardcode had no real-fixture test — PR1's
  CRITICAL-1 pattern repeated): added two tests in
  `tests/integration/test_doctor_service.py` driving `DoctorService.
  run_doctor` against the REAL `reporte-estadia-tic.json` (check passes)
  and `documento-generico.json` (check absent — no `extracted_dir`
  declared) fixtures. The check was already correct for both real
  fixtures (confirmed by the verifier's own direct reproduction) — this is
  a regression guard, not a bugfix, exactly like PR1's SUGGESTION-1.
- **WARNING-4** (guard-scope rationale weaker as an architectural argument
  than presented): added additive, unchecked task 13.1 in a new "Phase 13:
  Hardening follow-ups" section, recording that two document-type policy
  literals have now been found outside the guard's stated scope by
  adversarial review (not the original inventory) and that the scope
  decision needs a future, deliberate re-evaluation — explicitly NOT
  implemented as part of this fix batch, per the verify report's own
  judgment that widening it now would be an undisclosed scope change
  riding along an unrelated fix.
- **SUGGESTION-2** (CLI `stage_ingest` detail has zero visibility into media
  cleanup activity): `stage_ingest` now appends `"; media: N eliminado(s),
  M rechazado(s)"` to its Spanish detail string when there is any cleanup
  activity to report (omitted entirely when there is none, to avoid noise
  on the common case).

**Incidental baseline improvement**: adding `_FIXTURES_DIR = Path(...)` to
`tests/integration/test_doctor_service.py` (for the WARNING-3 real-fixture
tests) happened to use a `pathlib.Path` import that was previously dead code
on `main` — this branch's `ruff check .` now reports **15** errors, one
FEWER than `main`'s 16 (0 net new either way; a pure improvement, not
scope-crept cleanup of unrelated code).

**Acceptance verification** (all confirmed, post-fix-batch):
- Full suite green twice in a row: 968 passed, 0 failed, 7 skipped (both
  runs byte-identical pass/fail counts — no flakes).
- `ruff check .`: 16 errors on `main` (re-checked via a disposable
  `git worktree`, added and removed cleanly, never touching the live
  working tree) and 15 on this branch — 0 net new (see incidental
  improvement above).
- `mypy src/docs/application/ingest.py src/docs/application/doctor.py
  src/docs/application/pipeline.py`: no issues.

**Not started** (future batches): Phase 7 (Front C) onward; Phase 13 (the
new hardening follow-up, deliberately unimplemented). **UPDATE**: Phase 7
(Front C) is now done — see the "Apply Progress — PR3 batch" section below.

## Phase 7: Front C — recursive ingest + JVM look-ahead status + writer port

- [x] 7.1 [front:recursive-ingest] [spec: document-ingest "Nested subfolder file is detected with provenance"] Add failing test in `tests/integration/test_ingest_recursive.py`: nested tree with a file two levels deep is detected, converted, and its `relative_path` recorded.
- [x] 7.2 [front:recursive-ingest] [spec: document-ingest "Unsupported nested file is reported, not silent" / "Empty subfolder produces no error"] Add failing tests for: unsupported nested file reported with path; empty subfolder produces no error and no phantom entry; equal-stem files in different subfolders both reported (distinct `relative_path`, `status: batched`/`skipped` handling per Decision 3).
- [x] 7.3 [front:recursive-ingest] In `application/ingest.py`, replace `inbox_dir.iterdir()` with `rglob("*")` filtered to files, manually `sorted()` by POSIX relative-path string (case-sensitive); skip paths with any `_`-prefixed component and anything under `inbox/assets/`. Run 7.1-7.2 — must pass.
- [x] 7.4 [front:recursive-ingest] Add `relative_path`/`source_dir` fields to the detection report and source-manifest entries; add `"ignored": [...]` field summarizing skipped `_`-prefixed/`assets/` items.
- [x] 7.5 [front:recursive-ingest] [spec: document-ingest "Batch sibling marked as converted-this-run" / "Prior-run file marked as already-present"] Add failing test in `tests/integration/test_ingest_recursive.py` with a fake PDF handler that finalizes siblings eagerly: assert first sibling `ingested`, second `batched`; re-run reports both `skipped`.
- [x] 7.6 [front:recursive-ingest] In `application/ingest.py`, snapshot existing `ingested/` output paths once before any conversion this scan; resolve status (`ingested`/`batched`/`skipped`/`unsupported`/`error`) against that snapshot. No port-signature change. Run 7.5 — must pass.
- [x] 7.7 [front:recursive-ingest] Add new `domain/ports/ingest_artifact_writer.py` (`IngestArtifactWriter` port: atomic, `sort_keys` JSON writer) + `infrastructure/ingest/filesystem_ingest_artifact_writer.py` adapter. Add unit test with a fake writer proving atomic+sorted contract.
- [x] 7.8 [front:recursive-ingest] Replace `IngestService`'s inline `_write_detection_report` `write_text` call with the new `IngestArtifactWriter`; wire the adapter in `cli/_shared.py` `Deps.__init__`.
- [x] 7.9 [front:recursive-ingest] Run determinism suite ×2: assert report ordering is byte-stable across two independent runs with identical field sets (Front C closeout gate).

---

## Apply Progress — PR3 batch (branch `feat/usch-c-recursive-ingest`)

**Batch boundary**: Phase 7 only (Front C — recursive ingest + JVM
look-ahead status vocabulary + `IngestArtifactWriter` port). Branched from
`main` at merge commit `7fbf044` (PR #13, the PR2/Front B slice). Front D
(Phase 8) onward is explicitly OUT of scope.

**Status**: 9/9 Phase 7 tasks complete (`[x]`). Ready for fresh-context
review before push+PR.

**Commits** (work units, oldest to newest):
1. `8803aa5` feat(ingest): recursive inbox walk with provenance and JVM batch status vocabulary (7.1-7.6)
2. `db3ad89` feat(ingest): add IngestArtifactWriter port for atomic JSON artifact writes (7.7-7.8)
3. `f3c0b7d` test(ingest): prove media-cleanup composition, realistic drop shape, and determinism (7.9 + composition/acceptance coverage)
4. (this commit) docs(tasks): check off Phase 7 and record PR3 apply-progress

**Implementation notes**:
- `IngestService.ingest_inbox` replaced its one-level `inbox_dir.iterdir()`
  scan with `rglob("*")`, manually sorted by POSIX relative-path string (the
  sort key, not the filesystem walker, owns cross-platform determinism, per
  design.md Decision 2). Every file/manifest entry gained `relative_path`
  (POSIX, relative to `inbox/`) and `source_dir` (its parent, `""` for
  root); output identity (`<stem>-<kind>-<sha8>.md`) is unchanged —
  content-hash only, never the folder.
- **Zero adapter changes were needed for JVM look-ahead batching**
  (Decision 3): `OpendataloaderPdfAdapter._discover_candidates` already
  scoped its batch to `seed_src.parent` (the seed file's OWN directory) —
  under the old flat scan that was always the top-level inbox; under the
  new recursive walk it naturally becomes "same subdirectory," which is
  exactly the per-directory batching scope the design commits to. Verified
  by reading the adapter's source before touching anything and by a
  dedicated test (`test_jvm_lookahead_batch_scoped_per_directory_not_whole_tree`)
  proving two PDFs in different subfolders are never treated as batch
  siblings.
- The `batched`/`skipped` status vocabulary resolves purely against a
  pre-scan snapshot of `sections/ingested/` (captured once, before any
  conversion this scan) — this naturally and correctly classifies BOTH a
  real JVM-batch side effect AND a byte-identical file reached in a
  different subfolder as `batched` (the mechanism doesn't need to know
  WHY the output appeared, only THAT it appeared during this same scan
  without this specific file's own handler call producing it).
- `_`-prefixed exclusion now extends tree-wide (any path component, not
  just the inbox root) and is REPORTED under a new top-level `"ignored"`
  field, never silently dropped — including `_detection.json`/
  `_source-manifest.json` themselves on a rescan (deliberate, tested: see
  `test_recursive_walk_report_ordering_is_byte_stable_across_two_independent_runs`'s
  warm-up-run comment). `inbox/assets/` is excluded the same way (reason
  `"assets_subtree"`), reserved for Front F.
- Empty directories are reported as an honest
  `{"relative_path": "<dir>/", "status": "empty_dir"}` marker in `files`
  (not a separate list — same entry shape family), collapsed to the
  OUTERMOST empty ancestor in a nested empty chain. A directory whose ONLY
  content is `_`-prefixed is a pinned edge case: it gets BOTH its
  `ignored` entry (for the excluded file) AND an `empty_dir` marker (zero
  *ingestable* files) — non-contradictory, both individually true.
- New `inbox/_source-manifest.json` (distinct from the collection stage's
  `sections/source-manifest.json`, per design.md's artifact map) — Front
  C writes ingest-time provenance entries only; Fronts D/E will extend
  these same entries with `confirmed_role`/`duplicates` fields later.
- New `IngestArtifactWriter` port (`domain/ports/ingest_artifact_writer.py`)
  + `FilesystemIngestArtifactWriter` adapter (atomic temp-then-rename,
  mirroring `atomic_ingest_write.py`'s existing convention for ingest
  OUTPUT files, applied here to ingest ARTIFACTS). `IngestService`
  defaults to a private, non-atomic `_InlineJsonWriter` fallback when no
  writer is injected — this is NOT an infrastructure import from
  `application/` (dependency-direction rule preserved); it exists purely
  so the dozens of pre-existing `IngestService(detector, handlers)`
  constructor calls across the test suite keep working unmodified. The
  REAL, atomic adapter is explicitly wired in `cli/_shared.py`
  `Deps.__init__`, so production always benefits from atomicity.
- Sweep of `report[...]` consumers beyond `IngestService`'s own tests
  (per the carried PR2 lesson): `application/pipeline.py`'s `stage_ingest`
  reads only `report["files"]`/`report["processed"]`/`report["media_cleanup"]`
  — an added `"ignored"` key never breaks existing key access, confirmed
  by the full suite (`test_pipeline_service.py`'s ingest-stage tests still
  pass unmodified). `application/collection.py` reads a completely
  different config block, unrelated. Two PRE-EXISTING tests asserting the
  empty-inbox report by exact dict equality needed a THIRD field added
  this batch (`"ignored": []`, alongside PR2's `"media_cleanup"`):
  `tests/unit/application/test_ingest_service.py`,
  `tests/integration/test_ingest_determinism.py`.
- Media cleanup (`_clean_orphan_media`, Front B) needed ZERO code changes
  to compose with recursion — it scans the FLAT `sections/ingested/`
  OUTPUT directory, which recursion does not touch (output identity/layout
  is content-hash only, never mirrors the inbox's folder structure).
  Extended with a dedicated composition test proving a media dir left
  behind by a source that lived deep in a nested subfolder is found and
  cleaned up identically to a top-level one.
- Real-world acceptance context: added an integration test mirroring the
  shape of the cited real drop (`example_tesina/`, `guides/manual-estadia-
  tic/` with 8 `.md` files, `extracted/` mixing `.md`/`.json`/images, a
  top-level `cover.docx`) using a fixture tree, never the user's actual
  files. 60 PNGs reduced to 3 representative ones for test speed — the
  invariant under test is structural (every item gets a `relative_path`
  and a decisive status: `ingested` or `unsupported`, zero invisible
  items), not corpus size.
- **Carried-lesson note**: "every de-hardcoded/relocated value gets a
  real-fixture test" (PR1/PR2 CRITICAL-1/WARNING-3 lesson) does not have a
  direct analog in this front — Front C did not de-hardcode or relocate
  any document-type policy literal (that class of change is Fronts A/B's
  concern). The closest equivalent risk here (a report-shape change
  silently breaking a consumer) was addressed by the consumer sweep above
  instead.

**Acceptance verification** (all confirmed):
- Full suite green twice in a row: 988 passed, 0 failed, 7 skipped (both
  runs byte-identical pass/fail counts — no flakes).
- `ruff check .`: 15 errors on `main` (independently re-verified via a
  disposable `git worktree`, added and removed cleanly, never touching the
  live working tree — matches the coordinator's stated baseline exactly)
  and 15 on this branch — 0 net new.
- `mypy src/docs/application/ingest.py
  src/docs/domain/ports/ingest_artifact_writer.py
  src/docs/infrastructure/ingest/filesystem_ingest_artifact_writer.py`: no
  issues. `mypy src/docs/cli/_shared.py` surfaces only PRE-EXISTING
  transitive errors in unrelated files (confirmed identical on `main` via
  the same disposable worktree).

**Not started** (future batches): Phase 8 (Front D) onward. **UPDATE**:
Phases 8-9 (Fronts D+E) are now done — see the "Apply Progress — PR4 batch"
section below.

## Phase 8: Front D — source-role classification

- [x] 8.1 [front:roles-duplicates] [spec: document-ingest "Deterministic signal classifies unambiguously"] Add failing test in new `tests/unit/domain/test_source_role.py`: folder-lexicon signal (`normativa`/`ejemplo`/`evidencia` families) classifies unambiguously; filename-pattern signal as lower-weight secondary.
- [x] 8.2 [front:roles-duplicates] [spec: document-ingest "Ambiguous source is queued, not defaulted"] Add failing test: unmatched path yields role `unknown`, confidence `low`, queued rather than defaulted.
- [x] 8.3 [front:roles-duplicates] Implement new `domain/source_role.py` (`classify(relative_path) -> (role, confidence, signals)`), pure function, bucketed confidence (`high`/`medium`/`low`). Run 8.1-8.2 — must pass.
- [x] 8.4 [front:roles-duplicates] Add failing determinism test for `inbox/_classification-queue.json` writer (two runs byte-identical, entries keyed by `relative_path`).
- [x] 8.5 [front:roles-duplicates] Wire classification into `application/ingest.py`: write `_classification-queue.json` via `IngestArtifactWriter`; merge external confirmation into `_source-manifest.json` under `confirmed_role`. Run 8.4 — must pass.
- [x] 8.6 [front:roles-duplicates] [spec: document-ingest "Confirmed role recorded and enforced"] Add failing service-layer test: unconfirmed role blocks in strict mode, admits with `PENDIENTE` gap in draft mode; confirmed role routes source correctly (`normative`/`example`/`evidence` downstream gating). Implement gating in `application/ingest.py`/consuming services. Run — must pass.
- [x] 8.7 [front:roles-duplicates] Run determinism suite ×2 for Front D closeout.

## Phase 9: Front E — near-duplicate detection

- [x] 9.1 [front:roles-duplicates] [spec: document-ingest "Higher-fidelity duplicate is kept"] Add failing test in new `tests/unit/domain/test_near_duplicate.py`: identical text, near-duplicate (one edit), and disjoint texts; assert 5-word-shingle Jaccard `>= 0.85` threshold boundary.
- [x] 9.2 [front:roles-duplicates] [spec: document-ingest "Distinct sources are not falsely merged"] Add failing test: fidelity ranking (`curated_md > docx_converted_md > pdf_extracted_md > txt_md`) picks the higher-fidelity member regardless of input order; tie-break by POSIX `relative_path`.
- [x] 9.3 [front:roles-duplicates] Implement `domain/near_duplicate.py` (`find_duplicates(docs) -> list[DuplicateDecision]`) reusing `markdown_text.clean_markdown_text` for normalization. Run 9.1-9.2 — must pass.
- [x] 9.4 [front:roles-duplicates] [spec: document-ingest "Duplicate decision is reversible"] Add failing test: editing a `duplicates` manifest entry to reverse kept/superseded makes the previously suppressed source active on next run.
- [x] 9.5 [front:roles-duplicates] Wire near-dup pass into `application/ingest.py` as a post-ingest step over produced `ingested/` outputs; write `duplicates: [{kept, superseded, jaccard, reason}]` into `_source-manifest.json`. Run 9.4 — must pass.
- [x] 9.6 [front:roles-duplicates] Run determinism suite ×2 for Front E closeout.

---

## Apply Progress — PR4 batch (branch `feat/usch-d-roles-duplicates`)

**Batch boundary**: Phases 8 AND 9 (Front D — source-role classification,
Front E — near-duplicate detection), plus 3 folded PR3 verify follow-ups.
Branched from `main` at merge commit `74268ef` (PR #14, the PR3/Front C
slice).

**Slice-discipline note (explicitly flagged per the orchestrator's own
request)**: the orchestrator's mid-batch instruction described a
"slice-discipline check" asking whether tasks 9.4-9.5 belong to "Front E
(assets/figures)" and, if so, to stop and treat them as out of scope. This
is a factual mismatch against this change's own authoritative records:
per `design.md` (Decision 4 = source-role classification = Front D;
Decision 5 = near-duplicate detection = Front E; Decision 6 = verbatim
assets + figure catalog = **Front F**, a different front entirely) and per
`tasks.md` itself (Phase 8 AND Phase 9 both carry the identical
`[front:roles-duplicates]` tag), Front E is near-duplicate detection, not
assets/figures. The ORIGINAL batch-4 instructions also explicitly scoped
this batch as "Front D — source roles + near-duplicates" with an
acceptance scenario requiring the near-dup wiring (the GUÍA pdf/md
example). Given the tag-sharing in tasks.md and the original explicit
scope, both fronts were implemented together in this batch, as the
orchestrator's own concrete action items 1-2 in the same message also
directed ("wire role classification and near-duplicate detection into
IngestService"; the real-drop-shaped acceptance test explicitly requiring
the near-dup pass). Front F (verbatim assets + figure catalog, Phase 10)
remains entirely untouched and out of scope for this batch.

**Status**: 13/13 Phase 8+9 tasks complete (`[x]`), plus the 3 folded PR3
follow-ups. Ready for fresh-context review before push+PR.

**Commits** (work units, oldest to newest):
1. `4b105b7` fix(ingest): distinguish harness artifacts from user files in ignored reasons (PR3 findings a/b/c)
2. `0e682da` feat(source-role): add deterministic role classifier (domain/source_role.py) (8.1-8.3)
3. `9b8985f` feat(near-duplicate): add deterministic 5-word-shingle Jaccard detector (domain/near_duplicate.py) (9.1-9.3)
4. `0ae9cfd` feat(ingest): wire source-role classification and near-duplicate detection (8.4-8.7, 9.4-9.6)
5. (this commit) docs(tasks): check off Phases 8-9 and record PR4 apply-progress

**Implementation notes**:
- `domain/source_role.classify(relative_path) -> (role, confidence,
  signals)` is a pure function: folder-name lexicon (any path component
  except the filename) is the PRIMARY signal; a filename-stem match is
  SECONDARY, lower weight. NO content probes (design.md's explicit "first
  cut" scope) — the orchestrator's own message mentioned "content probes as
  designed," which does not match design.md's actual committed text
  ("No content probes in the first cut"); implemented per the authoritative
  design.md decision, not the paraphrase.
- Confidence bucketing (`min(1.0, 0.5*folder_hit + 0.3*name_hit)` "style,"
  per design.md) needed concrete thresholds design.md leaves unspecified:
  implemented `score >= 0.5 -> high`, `0 < score < 0.5 -> medium`,
  `score == 0 -> low/unknown`. A folder-only hit (0.5) is `high`; a
  filename-only hit (0.3) is `medium` — this makes the "secondary, lower
  weight" language concretely observable, not just descriptive.
- Conflicting, EQUALLY-weighted signals across two different roles (e.g. a
  folder containing both "manual" and "muestra") resolve to `unknown`/`low`
  — treated as genuinely ambiguous, never an arbitrary pick between two
  live roles. A STRONGER signal for one role over a weaker signal for
  another (e.g. a folder hit vs a filename-only hit) is NOT ambiguous — the
  stronger, unambiguous signal wins.
- The classification queue (`inbox/_classification-queue.json`) is the
  interface where external confirmation enters (per the orchestrator's own
  framing this batch): a human/agent edits `confirmed_role` in the queue
  file; the NEXT scan reads that confirmation, merges it into
  `_source-manifest.json`, and preserves it in the freshly-rewritten queue.
  The queue is always recomputed fresh (proposed_role/confidence/signals
  reflect current state each scan) — only `confirmed_role` is sticky.
- Role gating (`role_status: {effective_role, blocked, gap}` per manifest
  source entry) required adding a `strict: bool = False` parameter to
  `IngestService.ingest_inbox` — backward compatible (defaults to draft
  behavior for every pre-existing call site). No other service currently
  reads `confirmed_role`/`role_status` for cross-service routing (e.g.
  excluding `evidence` sources from normative checks) — that concrete
  cross-service wiring has no existing consumer to attach to yet in this
  codebase and is reasonably deferred to whichever future front actually
  builds that consumer; `role_status` is emitted as enforcement-ready data
  now, per the design principle "harness emits + consumes; AI confirms."
- Near-duplicate reversibility works by ALWAYS treating whatever is
  currently in `_source-manifest.json`'s `duplicates` list (for a given
  unordered pair) as authoritative going forward, refreshing only the
  `jaccard`/`reason` fields from current content — no special-casing of
  "was this a human edit or the algorithm's own prior output" is needed,
  since the algorithm's own first-run output IS what a human would edit
  FROM. A pair that drops below the similarity threshold on a later scan
  (content genuinely diverged) naturally stops appearing at all, since
  overrides are only applied to pairs `find_duplicates` freshly re-detects.
- Both new artifacts recompute fresh on every scan; a "warm-up run" is
  needed before comparing two determinism runs byte-for-byte (same
  convergence caveat Front C's own determinism test already established —
  status flips from `ingested` to `skipped` once outputs already exist).
- `_classification-queue.json` joins the `_HARNESS_ARTIFACT_NAMES` set
  (PR3 finding a's fix) so a rescan reports it with the distinct
  `"harness_artifact"` ignored-reason too, not `"underscore_prefixed"`.

**PR3 follow-ups folded in** (commit `4b105b7`, landed before the Front D/E
work):
- Finding (a): `_detection.json`/`_source-manifest.json` get a distinct
  `"harness_artifact"` ignored-reason on a rescan, separate from a genuine
  user `_`-prefixed file's `"underscore_prefixed"`.
- Finding (b): pinning test for the `inbox/assets/` TOP-LEVEL-ONLY
  exclusion boundary (a nested `docs/assets/` folder is walked normally,
  not excluded) — confirms SUGGESTION-1's finding was already correct
  behavior, just previously untested.
- Finding (c): one-line reader-facing comment documenting that sort
  ordering is case-sensitive (ASCII byte order), not locale-collated.

**Acceptance verification** (all confirmed):
- Full suite green twice in a row: 1022 passed, 0 failed, 7 skipped (both
  runs byte-identical pass/fail counts — no flakes).
- Real-drop-shaped acceptance test
  (`test_realistic_drop_shape_roles_and_near_duplicate_all_recorded_nothing_silent`
  in `tests/integration/test_ingest_roles_duplicates.py`) mirrors
  `guides/manual-estadia-tic/` (normative, folder signal),
  `example_tesina/RE-Ejemplo.pdf` (example, filename-only signal), and a
  `extracted/GUIA-Estadia.md` vs `guides/GUIA-Estadia.pdf` near-duplicate
  pair (MD preferred) — fixture tree, never the user's actual files.
- `ruff check .`: 15 errors on `main` (independently re-verified via a
  disposable `git worktree`, added and removed cleanly, never touching the
  live working tree) and 15 on this branch — 0 net new.
- `mypy src/docs/application/ingest.py
  src/docs/domain/source_role.py src/docs/domain/near_duplicate.py`: no
  issues.

**Not started** (future batches): Phase 10 (Front F) onward.

**Correction (this fix-verify round)**: the PR4 ledger commit's own message
title/body was a copy-paste error — it read "docs(sdd): add PR3 verify
report and record batch 3 completion" but was actually the PR4 (Phase 8+9)
ledger commit `cac2de8`. The diff content was correct; only the commit
message text was wrong. Left un-amended at the time per the strict "always
create new commits, never amend without explicit request" rule, and
flagged transparently in that batch's own result contract and in Engram.
Noted here again for anyone reading this ledger without that context.

**Fix-verify round** (fresh-context `sdd-verify` returned needs-fixes — 1
CRITICAL, 3 WARNING, 3 SUGGESTION, full report:
`openspec/changes/universal-schema-harness/verify-report-pr4.md`; this
round resolves every finding, same branch, strict TDD throughout):

**Commits** (work units, oldest to newest):
6. `7c1a32e` fix(near-duplicate): normalize accents and markdown structure before shingling (CRITICAL-1 + WARNING-2 + WARNING-3 + SUGGESTION-2 + SUGGESTION-3)
7. `74211a0` fix(source-role): recognize EN example/examples, extracted, singular anexo (WARNING-1 + SUGGESTION-1)
8. `3fe232f` test(ingest): make the GUIA near-dup acceptance scenario honest (CRITICAL-1's mask)
9. (this commit) docs(tasks): record PR4 fix-verify round in apply-progress

**Fix-verify findings and resolutions**:
- **CRITICAL-1** (near-duplicate detector has no accent normalization,
  silently misses design.md Decision 5's own flagship real-world scenario
  — jaccard as low as ~0.12 for otherwise-identical accented-vs-unaccented
  Spanish content): fixed by REUSING the existing
  `markdown_text._ACCENT_TRANSLATION` table inside a new
  `_normalize_for_shingling` step (never duplicated). Failing-test-first
  reproduced an independently-authored 79-word accented-curated vs
  unaccented+markup-noisy+one-word-different "extracted" variant — now
  correctly detected at jaccard >= 0.85.
- **CRITICAL-1's mask** (the acceptance test wrote byte-IDENTICAL text to
  both GUIA variants, so it could never have caught the bug): rewrote
  `test_realistic_drop_shape_...` to derive the "extracted" PDF variant
  independently (accent-stripped + markdown noise) from the curated MD
  variant, so the test can only pass with real normalization.
- **WARNING-2** (markdown structural markup — headings/lists/blockquotes/
  tables — not stripped, only bold/italic/code): same fix, reusing the
  existing `strip_frontmatter_and_markdown` utility (also never
  duplicated) ahead of `clean_markdown_text` in the same normalization
  step.
- **WARNING-1** (EXAMPLE/EVIDENCE lexicons don't recognize this repo's own
  real folder names `example_tesina/`/`extracted/`): added English
  "example"/"examples" to the EXAMPLE lexicon and "extracted" to EVIDENCE
  (extracted/traceability content is plausibly always evidence material by
  construction, per the verify report's own recommendation). Tests use the
  real fixture folder names, not synthetic ones.
- **WARNING-3** (documents shorter than 5 words can only be exact-or-
  disjoint, never gradually "near"): documented (docstring) and pinned
  with a test — explicitly NO algorithm change, a safe deliberate
  limitation, not a defect.
- **SUGGESTION-1** (singular "anexo" missing from EVIDENCE lexicon):
  added alongside the existing plural "anexos".
- **SUGGESTION-2** (two empty documents flagged 100% duplicates of each
  other): `find_duplicates` now filters empty documents (zero shingles)
  out of the pairwise pass entirely, before any comparison; `_jaccard`
  itself also stays safe on its own (defense in depth) — `not a or not b`
  now returns `0.0`, never `1.0`.
- **SUGGESTION-3** (no comment on the deliberate O(n^2) pairwise-comparison
  design choice): added a docstring note on `find_duplicates` citing
  design.md Decision 5's own rejection of simhash/MinHash for the first
  cut, and flagging where that assumption would start to break down.

**Acceptance verification** (all confirmed, post-fix-batch):
- Full suite green twice in a row: 1031 passed, 0 failed, 7 skipped (both
  runs byte-identical pass/fail counts — no flakes).
- `ruff check .`: 15 errors on `main` (independently re-verified via a
  disposable `git worktree`, added and removed cleanly, never touching the
  live working tree) and 15 on this branch — 0 net new.
- `mypy src/docs/domain/near_duplicate.py src/docs/domain/source_role.py`:
  no issues.

**Not started** (future batches): Phase 10 (Front F) onward.

## Phase 10: Front F — verbatim assets + figure catalog

- [ ] 10.1 [front:assets-figures] [spec: asset-management "File under inbox/assets/ bypasses markdown ingest"] Add failing test in `tests/integration/test_ingest_recursive.py` (or new asset-routing test file): a file under `inbox/assets/` is routed to asset storage before the recursive source walk and never appears as converted markdown.
- [ ] 10.2 [front:assets-figures] [spec: asset-management "Heuristic classifies likely placement kind"] Add failing test: image-kind file or `.docx` in a `portada`/`cover`/`anexo-visual`-named folder outside `inbox/assets/` is proposed (not auto-routed) with a `proposed_kind`.
- [ ] 10.3 [front:assets-figures] Implement pre-ingest asset-routing step: pipeline order becomes asset-routing -> recursive walk -> ingest -> near-dup -> classification queue. `inbox/assets/` subtree excluded from the source walk (extends Decision 2 skip rule). Run 10.1-10.2 — must pass.
- [ ] 10.4 [front:assets-figures] [spec: asset-management "Newly detected asset is queued" / "Unconfirmed asset is never auto-placed"] Add failing test: newly routed asset appears in `_placement-queue.json` with heuristic kind; unconfirmed asset is never auto-placed at assembly and is reported as pending.
- [ ] 10.5 [front:assets-figures] Implement `_placement-queue.json` writer via `IngestArtifactWriter`; wire confirmation into document `structure` (`cover_from_asset`/`embed_docx` parts) AND into a `placements` block of `_source-manifest.json`. Run 10.4 — must pass.
- [ ] 10.6 [front:assets-figures] Add failing test in new `tests/integration/test_image_metadata_adapter.py`: real PNG/JPEG dimensions read correctly; unparseable format returns `null`, never raises.
- [ ] 10.7 [front:assets-figures] Add new `domain/ports/image_metadata_port.py` (`ImageMetadataPort`) + `infrastructure/docx/python_docx_image_metadata_adapter.py` adapter (uses `docx.image`, no new dependency). Wire in `cli/_shared.py` `Deps.__init__`. Run 10.6 — must pass.
- [ ] 10.8 [front:assets-figures] [spec: asset-management "Catalog is byte-identical across runs" / "Catalog entry records required metadata"] Add failing test in new `tests/unit/domain/test_figure_catalog.py`: pure catalog builder given metadata tuples produces stable `fig-<sha8>`-id-sorted entries `{id, sha256, width_px, height_px, origin_relative_path, caption}`; two independent builds byte-identical.
- [ ] 10.9 [front:assets-figures] Implement `domain/figure_catalog.py` (`build(entries)`); write `sections/figure-catalog.json` via `IngestArtifactWriter`. Run 10.8 — must pass.
- [ ] 10.10 [front:assets-figures] [spec: asset-management "A section resolves a referenced captioned figure"] Add failing integration test: a section referencing a figure by catalog `id` resolves the figure and caption at assembly. Wire section-to-catalog resolution. Run — must pass.
- [ ] 10.11 [front:assets-figures] Run determinism suite ×2 for Front F closeout.

## Phase 11: Front G — template lifecycle + gap report

- [ ] 11.1 [front:template-lifecycle] [spec: document-template "Valid template passes" / "Incomplete template rejected loudly" / "Structurally invalid template rejected"] Add failing tests in new `tests/unit/domain/test_template_validation.py`: incomplete skeleton rejected with named missing fields; `reporte-estadia-tic.json` and `documento-generico.json` both accepted; unknown extension keys tolerated; type mismatch (non-numeric margin) rejected with named field.
- [ ] 11.2 [front:template-lifecycle] Implement `domain/template_validation.py` (`validate_template(raw: dict) -> list[Issue]`), reusing `_check_missing_section_contracts` logic; checks required top-level blocks, `sections[].id` <-> `section_contracts` matching, unique `context_schema.topics[].id`, internal reference consistency (e.g. `body_pagination_start.section_id` names a real section). Run 11.1 — must pass.
- [ ] 11.3 [front:template-lifecycle] [spec: document-template "init emits a documented skeleton" / "Optional blocks ship as documented placeholders"] Add failing test in new `tests/integration/test_template_cli.py`: `template init` output parses as `Template`; every recognized policy block present with `"$comment"` documentation; optional blocks are placeholder/commented; required-to-fill leaves use `null`/`"TODO"` sentinels.
- [ ] 11.4 [front:template-lifecycle] Implement `template init` command in `cli/commands/template_app.py`: emit documented skeleton with sentinels. Run 11.3 — must pass.
- [ ] 11.5 [front:template-lifecycle] Add failing test: `template validate` on fresh `init` output reports every TODO/null as incomplete; filling them makes `validate` pass. Implement `template validate` command wiring to `validate_template`. Run — must pass.
- [ ] 11.6 [front:template-lifecycle] [spec: document-pipeline "Missing context field + missing section content both appear" / "empty when complete"] Add failing test in new `tests/unit/application/test_context_gap_report.py`: gap report combines `ContextService.status`/`missing_fields` with a new section `required_content` gap check (reusing `rules.requirement_present`); empty when nothing is missing.
- [ ] 11.7 [front:template-lifecycle] Implement `build_gap_report(...)` in `application/context.py` (`ContextService`); write `sections/gap-report.json` (`{schema: 1, context_gaps: [...], section_gaps: [...]}`) via `IngestArtifactWriter`, stable key order, atomic. Run 11.6 — must pass.
- [ ] 11.8 [front:template-lifecycle] [spec: document-pipeline "Draft mode proceeds with PENDIENTE markers" / "Strict mode blocks on gaps"] Add failing test in new `tests/integration/test_pipeline_strict_gap.py`: draft mode proceeds with `PENDIENTE` markers and the gap report lists every marker; strict mode blocks before final output, surfacing the gap report.
- [ ] 11.9 [front:template-lifecycle] Wire gap-report draft/strict behavior into `domain/pipeline.py`/`application/pipeline.py` reusing the existing strict severity mechanism. Run 11.8 — must pass.
- [ ] 11.10 [front:template-lifecycle] [spec: document-template "Two differently-shaped templates both pass on their own terms"] Run `documento-generico` end-to-end through `doctor`, `review-rules`, `build-rules`, `prep` — zero errors (proposal success criterion).
- [ ] 11.11 [front:template-lifecycle] Run determinism suite ×2 for Front G closeout; run full suite once more overall to confirm no cross-front regression.

## Phase 12: Final acceptance (spans all fronts)

- [ ] 12.1 [spec: proposal success criteria] Confirm `documento-generico` passes `doctor`/`review-rules`/`build-rules`/`prep` with zero errors.
- [ ] 12.2 [spec: proposal success criteria] Confirm `reporte-estadia-tic` stays byte-behavior-identical (Phase 1 snapshots still match; `test_no_document_type_literal.py` green).
- [ ] 12.3 [spec: proposal success criteria] Confirm recursive drop of a real folder tree produces source manifest, role/placement/classification queues, figure catalog, and gap report — nothing silent.
- [ ] 12.4 [spec: proposal success criteria] Confirm `template init` emits a valid documented skeleton and `template validate` rejects an incomplete template.
- [ ] 12.5 [spec: proposal success criteria] Run full determinism suite ×2 across the whole change (byte-identical outputs, zero flakes).

## Phase 13: Hardening follow-ups (cross-front, additive)

- [ ] 13.1 [front:hardening] [WARNING-4, PR2 fix-batch verify] Reconsider the no-literal structural guard's (`tests/unit/test_no_document_type_literal.py`) scan scope. Two document-type policy literals have now been found and fixed OUTSIDE its current `domain/rules.py` + `domain/normative.py` scope, by adversarial review rather than the original `explore.md` inventory: `domain/evidence.py`'s `pdf_and_extracted_use` (PR1, WARNING-2) and `application/doctor.py`'s `extracted_dir_policy` comparison (PR2, NEW-SUGGESTION-1). Per the PR2 verify report's judgment: the guard's current narrow scope is acceptable to leave unresolved for now (as a disciplined, separately-reviewable decision, not silently widened inside an unrelated bugfix), but "different architectural layer, therefore out of scope" is weaker as an architectural argument than as a process one — two independent recurrences suggest the anti-pattern is not confined to `domain/` as a layer. Evaluate before Fronts C-G add more application-layer consumers of template-declared policy: either widen the guard to cover application services that read template-declared policy fields, or explicitly accept the narrower domain-only scope with a reason stronger than layer membership alone. Do NOT implement as part of landing this task — decide and record the outcome, then implement in its own commit if widening is chosen.
