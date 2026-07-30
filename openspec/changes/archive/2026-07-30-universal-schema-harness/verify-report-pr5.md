# Verify Report -- PR5 (Front F: verbatim assets, placement queue, figure catalog)

Change: universal-schema-harness | Branch: feat/usch-f-assets-figures
Base: main @ 7839e0f (merge of PR4, feat/usch-d-roles-duplicates)
Scope: Phase 10 (10.1-10.11, 11 tasks). Front G (Phase 11-12) intentionally
not implemented -- not evaluated here except for slice-discipline leakage.
Reviewer: sdd-verify (fresh-context adversarial review, fifth target in
this change)

## Executive Summary

PR5 is mechanically solid (1054/1054 tests pass twice, ruff 15 matches
current main exactly, mypy clean, no new runtime dependency, clean
layering) and the self-caught design correction (46e9415, heuristic
candidates excluded from markdown ingest) is genuinely fixed --
independently reproduced end to end. But this review found 1 CRITICAL,
undisclosed gap that the coordinator's priority probes did not directly
name: task 10.5's own stated deliverable ("wire confirmation into document
structure -- cover_from_asset/embed_docx parts") and a spec scenario
explicitly titled "Confirmed placement is recorded and usable" ("assembly
can reference the asset at its confirmed placement") are NOT satisfied --
confirmed placements are recorded in the manifest and the asset file is
physically copied to disk, but nothing ever injects the computed
structure_part into config["structure"], which is what docx_assembly.py/
doctor.py actually read. Empirically proven: a confirmed cover placement
is completely invisible to structure_parts(config) without a separate,
undocumented manual edit. Unlike task 10.10's figure-resolver gap (which
IS honestly, explicitly disclosed with a clear scope note), this gap has
no disclosure anywhere in the apply-progress, and task 10.5 is checked off
complete. 2 WARNINGs cover the honest-but-literal-spec-mismatch of task
10.10, and the broad real-world scope of the image heuristic (sweeps up
PDF-extraction images, not just cover/portada candidates). Verdict:
needs-fixes.

## CRITICAL-1 -- Confirmed asset placement is never wired into the document structure; "assembly can reference the asset" is not true, and this gap is undisclosed

- Where: src/docs/application/ingest.py, _route_and_queue_assets /
  _structure_part_for_kind. Consumer side: src/docs/domain/docx_structure.py
  structure_parts(config), read by docx_assembly.py, doctor.py, and the
  audit adapters.
- Task 10.5's own literal text: "Implement _placement-queue.json writer...
  wire confirmation into document structure (cover_from_asset/embed_docx
  parts) AND into a placements block of _source-manifest.json." Only the
  SECOND half was delivered. Design.md Decision 6a: "Confirmation lands
  TWICE: confirmed placements are written into the document structure...
  AND recorded in a placements block... for audit." Only the audit half
  lands.
- Spec: asset-management, Requirement "Pending-Placement Queue and
  Placement Manifest", Scenario "Confirmed placement is recorded and
  usable" -- "GIVEN a queued asset whose placement has been confirmed
  externally... THEN the placement manifest records the confirmed
  placement AND assembly can reference the asset at its confirmed
  placement." The second AND-clause is false as implemented.
- Independently reproduced end to end: confirmed a cover.docx placement
  (edited _placement-queue.json, re-scanned), verified the asset was
  physically copied to assets_dir AND the manifest's placements entry
  correctly computed structure_part = {"type": "cover_from_asset", "asset":
  "cover.docx"}. Then built a minimal, unedited document config (the shape
  docx_assembly.py/doctor.py actually receive) and called the REAL,
  pre-existing structure_parts(config) consumer directly: it returned NO
  cover_from_asset entry. The confirmation is completely inert for
  assembly -- a human would need to separately, manually edit the
  document's own structure/overrides to add the cover_from_asset part
  themselves, a step nowhere documented in this front's workflow.
- IngestService has no access to a document's config/overrides at all (it
  only ever receives inbox_dir/sections_dir/assets_dir Path arguments) --
  architecturally, nothing in this PR's own code COULD write into "the
  document structure" without a new consumer reading _source-manifest.json's
  placements and merging it into Document.overrides, which does not exist.
  This is the same structural shape as task 10.10's disclosed gap
  (data produced, no consumer wired) -- but unlike 10.10, this one is not
  named as a scope boundary anywhere in tasks.md or the apply-progress; the
  apply-progress's own 10.10 note even contrasts it favorably against
  "cover_from_asset/embed_docx, which ALREADY HAD a working assembly-side
  consumer to wire into" -- true of the READ side (structure_parts already
  existed pre-PR5), but conflates that with the WRITE side (nothing writes
  a confirmed placement into what structure_parts reads), which this PR
  was specifically supposed to deliver per its own task 10.5 text.
- Existing test coverage matches this gap exactly: every placement test
  (test_confirmed_placement_recorded_in_manifest_and_asset_physically_
  routed, test_confirmation_survives_multiple_rescans) stops at asserting
  the manifest's placements entry and the physical file copy -- none call
  structure_parts or otherwise prove "assembly can reference the asset,"
  which is the spec scenario's own explicit second half.
- Recommendation: either (a) implement the missing write path (a
  consuming step -- during pipeline assembly or a dedicated CLI command --
  that reads inbox/_source-manifest.json's placements and merges confirmed
  structure_parts into the document's own structure/overrides before
  assembly), or (b) if deferring this to a future front, disclose it
  explicitly with the same honesty as task 10.10's scope note, and correct
  task 10.5's checkbox/description and the spec scenario's wording (or the
  spec itself) to reflect what actually ships now.

## 1. Priority Probe: Design Correction 46e9415 (self-caught -- extra scrutiny)

Independently reproduced end to end, not just read from the diff: a
top-level cover.docx dropped into a fresh inbox is (a) NEVER present in
report["files"], (b) NEVER written to sections/ingested/ as flattened
markdown, (c) honestly reported under report["ignored"] with reason
"asset_candidate", and (d) appears in _placement-queue.json with
proposed_kind "cover" and confirmed_placement null. This is a genuine fix,
independently confirmed, not just claimed. The pre-existing PR3 acceptance
test (test_realistic_multi_source_drop_produces_decisive_provenance_for_
every_item) was correctly updated to move cover.docx and the extracted/
PNGs from report["files"] into report["ignored"], with the reduced
report["processed"] count -- re-ran this test directly, passes.

### WARNING-1 -- The heuristic image-detection scope is broad enough to sweep up PDF-extraction images that are not really cover/back candidates

- Design.md's Decision 6a literally specifies "files whose kind is an
  image... anywhere" (not scoped to cover/portada-named folders) as
  heuristic candidates -- the implementation matches this faithfully, not
  a deviation.
- But this means a realistic drop's extracted/page-1.png,
  extracted/page-2.png, etc. (OCR-extraction byproduct images, not
  intended for cover/back placement) ALL become placement-queue entries
  needing external confirmation, instead of being reported as ordinary
  "unsupported" content the way they were before this front (confirmed via
  the updated PR3 test: they moved from report["files"]
  status="unsupported" into report["ignored"] reason="asset_candidate").
  For a real-world drop with dozens of extracted images (the coordinator's
  own cited real-drop shape has ~60 PNGs, reduced to 3 for test speed),
  this could produce a large, mostly-irrelevant placement queue that
  obscures the few genuine cover/portada candidates among it.
- Not a bug relative to design.md's own text -- a real product-shape
  observation worth a design-level follow-up (e.g., only heuristically
  propose images NOT under a folder that already signals non-asset intent,
  such as "extracted/", or lower-confidence-queue images differently from
  clearly-named ones) rather than a defect in this PR.

## 2. Priority Probe: Task 10.10 Scope Judgment

Independently confirmed the spec scenario 10.10 maps to
("A section resolves a referenced captioned figure") is written with an
explicit assembly-time precondition: "WHEN the document is assembled --
THEN the referenced figure and its caption resolve correctly." Task
10.10's own text likewise required "an integration test... resolves...
AT ASSEMBLY." Neither is delivered -- resolve_section_figures is a pure,
well-tested domain function with zero assembly-time integration test and
zero caller anywhere in docx_assembly.py (confirmed via a src/-wide grep:
the only caller of figure_catalog.build/resolve_section_figures is
ingest.py's own catalog-writing step; nothing reads sections/
figure-catalog.json downstream).

Judgment: HONEST, ACCEPTABLE slice boundary, not a silently-broken
feature -- in clear contrast to CRITICAL-1 above. The apply-progress's
scope note is explicit, accurately describes what was and was not built,
correctly cites the coordinator's own batch framing as the reason, and
draws the parallel to Front D's role_status precedent (also disclosed).
This is the right way to defer a capability: task 10.10 remains
technically "checked off" ahead of its literal assembly-time bar, but a
reviewer or future implementer reading tasks.md cannot miss the gap --
worth a WARNING for the checkbox/spec-wording mismatch (the task and spec
scenario as LITERALLY written are not satisfied, only the underlying
resolution LOGIC is proven correct in isolation), but not a trust
violation the way CRITICAL-1 is.

### WARNING-2 (tracking the above)

Recommend either loosening task 10.10's/the spec scenario's wording to
match what actually ships (a resolvable-but-not-yet-spliced capability),
or opening a tracked follow-up task (mirroring Phase 13's precedent from
PR1/PR2's own hardening-follow-ups pattern) for the actual assembly-time
splice, so "done" in tasks.md keeps meaning what it says elsewhere in this
change.

## 3. Priority Probe: Vacuous-Test Guard (PR4's lesson, checked)

- Figure-catalog dimensions test (test_image_metadata_adapter.py): uses a
  genuinely real, base64-decoded 1x1 pixel PNG (not a stub or a
  hand-typed fake header) and asserts EXACT dimensions (1, 1) -- this
  would fail if dimensions came back wrong, None, or guessed. A SEPARATE
  test feeds genuinely garbage bytes (b"this is not a real png file")
  named with a .png extension and asserts None, never raises. A third
  test checks a missing file also returns None. All three re-run
  independently and pass. Non-vacuous, confirmed.
- The real-drop acceptance test (test_real_drop_cover_convention_asset_
  and_catalog_images_all_visible) uses the REAL
  PythonDocxImageMetadataAdapter (not the file's own _FakeImageMetadata
  used by every other test in that file) specifically so the null-
  dimensions path is exercised honestly against real image-header
  parsing, not a stub that always returns a canned value -- confirmed via
  direct read of the test's own service construction.
- Heuristic-detection test (test_image_file_anywhere_is_heuristically_
  proposed): uses images/guia/page-001-image-001.png, a path with ZERO
  cover/portada/anexo-visual naming signal, and asserts proposed_kind is
  explicitly None (never invented) -- this is a genuinely ambiguous
  fixture, not a pre-labeled "cover.png"-style shortcut that would trivially
  pass regardless of the heuristic's actual logic.

## 4. Priority Probe: Placement Queue Contract

- External-confirmation only: read _read_prior_confirmed_placements
  directly -- the ONLY way confirmed_placement can be non-null is by
  reading it back from an EXISTING _placement-queue.json file; nothing in
  IngestService (or anywhere else in src/, confirmed via grep) ever writes
  a non-null confirmed_placement on its own initiative.
- Confirmations survive re-scans: independently reproduced beyond the
  existing test_confirmation_survives_multiple_rescans -- confirmed a
  cover placement, then re-ran ingest_inbox three times; the confirmation
  and the resulting structure_part held across every re-scan.
- Deterministic via IngestArtifactWriter: _placement-queue.json is written
  through the same atomic, sort_keys writer port as every other artifact
  in this change (self.writer.write_json(inbox_dir / _PLACEMENT_QUEUE_NAME,
  ...)) -- confirmed via direct code read, no new writer introduced.
- Unconfirmed asset never auto-placed/copied: independently reproduced --
  an unconfirmed heuristic image candidate produces no assets_dir entry at
  all (directory not even created) after a scan, only after external
  confirmation and a subsequent re-scan.
- Unparseable image -> dims null, never guessed: confirmed via the real
  adapter (Section 3 above) and via the acceptance test's own genuinely
  unparseable second PNG fixture.

## 5. Layering, Dependencies, Determinism, Consumer Sweep, Slice Discipline

- Layering: ImageMetadataPort (domain/ports/image_metadata_port.py) is a
  plain typing.Protocol; PythonDocxImageMetadataAdapter (infrastructure/
  docx/) is the sole implementation, imported and constructed ONLY in
  cli/_shared.py's Deps.__init__ -- confirmed via diff, no other file
  references the concrete adapter class.
- No new runtime dependency: confirmed pyproject.toml/uv.lock have zero
  diff in this branch; confirmed docx.image.image resolves to a module
  file physically inside the already-installed python-docx package
  (site-packages/docx/image/image.py), not a separate distribution.
- Determinism: re-ran the figure-catalog byte-identical-across-two-builds
  test directly; independently re-verified the full suite twice (see
  below) with no flakes.
- Report-shape consumer sweep: swept src/ for every consumer of
  report["placements"]/sections/figure-catalog.json beyond ingest.py's own
  production of them -- none exists (confirmed via grep), consistent with
  CRITICAL-1 and the 10.10 gap both being genuinely unconsumed data, not a
  masked breakage of some other feature.
- ignored-reason vocabulary stays coherent: independently reproduced --
  with all 4 harness-written artifacts present (_detection.json,
  _source-manifest.json, _classification-queue.json, and the NEW
  _placement-queue.json), a rescan reports every one of them under the
  distinct "harness_artifact" reason, never "underscore_prefixed" --
  confirming the PR3-fix's set was correctly extended, not weakened, and
  that the four reason values (harness_artifact / underscore_prefixed /
  assets_subtree / asset_candidate) do not collide (first-match-wins
  ordering in _walk_inbox is deliberate and correctly preserved).
- Slice discipline: confirmed via diff-stat and a targeted diff check for
  every Front G file path (domain/template_validation.py,
  cli/commands/template_app.py, application/context.py's gap-report
  additions): zero matches, zero diff. Only the files listed in the
  original diff-stat were touched.

## Independent Re-run Evidence (this pass)

- Full suite run twice independently: 1054 passed, 0 failed, 7 skipped
  both times, byte-identical counts. Matches the claimed count exactly.
- ruff check: 15 errors on this branch. Compared against CURRENT main
  (post-PR4-merge, commit 7839e0f tree) via a disposable git worktree
  (added and removed cleanly, never touching the live working tree) --
  also 15 errors, identical file:line violation set. 0 net new.
- mypy on all 6 touched/new files (ingest.py, figure_catalog.py,
  image_metadata_port.py, python_docx_image_metadata_adapter.py,
  pipeline.py, cli/_shared.py): no issues attributable to these files;
  the only reported errors are the same pre-existing transitive
  third-party-stub gaps observed in every prior pass of this change
  (opendataloader_pdf, filetype, defusedxml, docxcompose stub gaps,
  json_repository's pre-existing call-arg mismatch), unrelated to this
  PR's own code.
- Independently, empirically reproduced (not just read from the diff or
  trusted from existing tests): the cover.docx exclusion end to end;
  confirmed-placement persistence across 3 re-scans; the assembly-time
  structure_parts(config) gap (CRITICAL-1) by calling the real, unedited
  consumer directly; unconfirmed-candidate never-copied protection; the
  harness-artifact ignored-reason coherence across all 4 artifact files.
- No checkout-main-onto-live-tree mistake was made during this review; all
  main-baseline comparisons used a disposable git worktree add/remove.

## Issues Summary

| Severity | Count | Items |
|----------|-------|-------|
| CRITICAL | 1 | confirmed asset placement never wired into document structure; spec's "assembly can reference the asset" is false and undisclosed |
| WARNING | 2 | heuristic image-detection scope sweeps up PDF-extraction images; task 10.10's checkbox/spec wording promises assembly-time resolution that is honestly-but-not-formally deferred |
| SUGGESTION | 0 | none |

## Verdict

needs-fixes -- CRITICAL-1 is the deciding factor: a named spec scenario
("Confirmed placement is recorded and usable") is not satisfied, task
10.5 is checked off despite its own stated deliverable being half-missing,
and -- unlike every other deferred-scope decision found across this
entire change (Front D's role_status, this same PR's own task 10.10) --
this specific gap carries no disclosure anywhere in tasks.md or the
apply-progress. The mechanical foundation (asset routing, physical
copying, catalog building, queue confirmation/persistence, determinism,
layering, no new dependency) is genuinely solid and independently
verified throughout this pass; this is a scoping/disclosure gap on top of
solid infrastructure, not a broad quality problem. WARNING-1/2 are
lower-priority and independently deferrable.
