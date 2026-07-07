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
the design's slicing sketch, PR2 through PR7.
## Phase 6: Front B — orphan `_media/` cleanup

- [ ] 6.1 [front:first-use-bugs] [spec: document-ingest "Re-ingesting a source removes its stale media directory"] Add failing test in new `tests/unit/application/test_media_cleanup.py`: content-addressed `_media/` orphan (no current output references it) is removed.
- [ ] 6.2 [front:first-use-bugs] [spec: document-ingest "Referenced media is never deleted"] Add failing test in the same file: a file under `_media/` not matching the content-addressed pattern is refused (left in place, reported in `_detection.json.ignored`).
- [ ] 6.3 [front:first-use-bugs] Implement orphan cleanup step in `application/ingest.py` (runs during the ingest scan): remove only content-addressed orphans with no current reference; refuse and report anything else. Run 6.1-6.2 — must pass.
- [ ] 6.4 [front:first-use-bugs] Run determinism suite ×2 for Front B closeout.

## Phase 7: Front C — recursive ingest + JVM look-ahead status + writer port

- [ ] 7.1 [front:recursive-ingest] [spec: document-ingest "Nested subfolder file is detected with provenance"] Add failing test in `tests/integration/test_ingest_recursive.py`: nested tree with a file two levels deep is detected, converted, and its `relative_path` recorded.
- [ ] 7.2 [front:recursive-ingest] [spec: document-ingest "Unsupported nested file is reported, not silent" / "Empty subfolder produces no error"] Add failing tests for: unsupported nested file reported with path; empty subfolder produces no error and no phantom entry; equal-stem files in different subfolders both reported (distinct `relative_path`, `status: batched`/`skipped` handling per Decision 3).
- [ ] 7.3 [front:recursive-ingest] In `application/ingest.py`, replace `inbox_dir.iterdir()` with `rglob("*")` filtered to files, manually `sorted()` by POSIX relative-path string (case-sensitive); skip paths with any `_`-prefixed component and anything under `inbox/assets/`. Run 7.1-7.2 — must pass.
- [ ] 7.4 [front:recursive-ingest] Add `relative_path`/`source_dir` fields to the detection report and source-manifest entries; add `"ignored": [...]` field summarizing skipped `_`-prefixed/`assets/` items.
- [ ] 7.5 [front:recursive-ingest] [spec: document-ingest "Batch sibling marked as converted-this-run" / "Prior-run file marked as already-present"] Add failing test in `tests/integration/test_ingest_recursive.py` with a fake PDF handler that finalizes siblings eagerly: assert first sibling `ingested`, second `batched`; re-run reports both `skipped`.
- [ ] 7.6 [front:recursive-ingest] In `application/ingest.py`, snapshot existing `ingested/` output paths once before any conversion this scan; resolve status (`ingested`/`batched`/`skipped`/`unsupported`/`error`) against that snapshot. No port-signature change. Run 7.5 — must pass.
- [ ] 7.7 [front:recursive-ingest] Add new `domain/ports/ingest_artifact_writer.py` (`IngestArtifactWriter` port: atomic, `sort_keys` JSON writer) + `infrastructure/ingest/filesystem_ingest_artifact_writer.py` adapter. Add unit test with a fake writer proving atomic+sorted contract.
- [ ] 7.8 [front:recursive-ingest] Replace `IngestService`'s inline `_write_detection_report` `write_text` call with the new `IngestArtifactWriter`; wire the adapter in `cli/_shared.py` `Deps.__init__`.
- [ ] 7.9 [front:recursive-ingest] Run determinism suite ×2: assert report ordering is byte-stable across two independent runs with identical field sets (Front C closeout gate).

## Phase 8: Front D — source-role classification

- [ ] 8.1 [front:roles-duplicates] [spec: document-ingest "Deterministic signal classifies unambiguously"] Add failing test in new `tests/unit/domain/test_source_role.py`: folder-lexicon signal (`normativa`/`ejemplo`/`evidencia` families) classifies unambiguously; filename-pattern signal as lower-weight secondary.
- [ ] 8.2 [front:roles-duplicates] [spec: document-ingest "Ambiguous source is queued, not defaulted"] Add failing test: unmatched path yields role `unknown`, confidence `low`, queued rather than defaulted.
- [ ] 8.3 [front:roles-duplicates] Implement new `domain/source_role.py` (`classify(relative_path) -> (role, confidence, signals)`), pure function, bucketed confidence (`high`/`medium`/`low`). Run 8.1-8.2 — must pass.
- [ ] 8.4 [front:roles-duplicates] Add failing determinism test for `inbox/_classification-queue.json` writer (two runs byte-identical, entries keyed by `relative_path`).
- [ ] 8.5 [front:roles-duplicates] Wire classification into `application/ingest.py`: write `_classification-queue.json` via `IngestArtifactWriter`; merge external confirmation into `_source-manifest.json` under `confirmed_role`. Run 8.4 — must pass.
- [ ] 8.6 [front:roles-duplicates] [spec: document-ingest "Confirmed role recorded and enforced"] Add failing service-layer test: unconfirmed role blocks in strict mode, admits with `PENDIENTE` gap in draft mode; confirmed role routes source correctly (`normative`/`example`/`evidence` downstream gating). Implement gating in `application/ingest.py`/consuming services. Run — must pass.
- [ ] 8.7 [front:roles-duplicates] Run determinism suite ×2 for Front D closeout.

## Phase 9: Front E — near-duplicate detection

- [ ] 9.1 [front:roles-duplicates] [spec: document-ingest "Higher-fidelity duplicate is kept"] Add failing test in new `tests/unit/domain/test_near_duplicate.py`: identical text, near-duplicate (one edit), and disjoint texts; assert 5-word-shingle Jaccard `>= 0.85` threshold boundary.
- [ ] 9.2 [front:roles-duplicates] [spec: document-ingest "Distinct sources are not falsely merged"] Add failing test: fidelity ranking (`curated_md > docx_converted_md > pdf_extracted_md > txt_md`) picks the higher-fidelity member regardless of input order; tie-break by POSIX `relative_path`.
- [ ] 9.3 [front:roles-duplicates] Implement `domain/near_duplicate.py` (`find_duplicates(docs) -> list[DuplicateDecision]`) reusing `markdown_text.clean_markdown_text` for normalization. Run 9.1-9.2 — must pass.
- [ ] 9.4 [front:roles-duplicates] [spec: document-ingest "Duplicate decision is reversible"] Add failing test: editing a `duplicates` manifest entry to reverse kept/superseded makes the previously suppressed source active on next run.
- [ ] 9.5 [front:roles-duplicates] Wire near-dup pass into `application/ingest.py` as a post-ingest step over produced `ingested/` outputs; write `duplicates: [{kept, superseded, jaccard, reason}]` into `_source-manifest.json`. Run 9.4 — must pass.
- [ ] 9.6 [front:roles-duplicates] Run determinism suite ×2 for Front E closeout.

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
