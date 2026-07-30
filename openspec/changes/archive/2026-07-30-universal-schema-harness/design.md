# Design: Universal Schema Harness

> Phase: design | Artifact store: openspec | Language: English
> Depends on: `proposal.md` (Approach 1), `explore.md` (hardcoding inventory #1-13)
> Architecture: hexagonal (domain -> application -> infrastructure; composition root `cli/_shared.py`)

## The architecture in one paragraph

The `Template` model is **already** the universal schema the vision asks for
(`extra="allow"` + `Document.overrides` deep-merge at `Deps.resolve_context`).
This change stops `rules.py`/`evidence.py` from treating one document's declared
values as universal law, evacuates Spanish-thesis literals from domain code into
template data, and adds a family of **deterministic harness-emitted artifacts**
(recursive-ingest report, source manifest, classification/placement queues,
figure catalog, gap report, template skeleton). Every artifact is data the
harness *writes and reads* mechanically; the AI only fills validated slots and
confirms queues — never trusted at runtime. No new runtime dependency, no new
schema file, no rule DSL. The two existing fixtures become the acceptance tests:
`documento-generico` must pass clean, `reporte-estadia-tic` must stay
byte-behavior-identical.

## Design principles (binding, applied to every decision below)

| Principle | Consequence |
|-----------|-------------|
| Conditional, not literal | A check fires only when its block is *declared*, and validates *internal consistency* against the template's own values — never a hardcoded expected value. |
| Additive completeness, not strict typing | `Template` stays `extra="allow"`; completeness is enforced by a **separate** validator, so open extension survives. |
| Harness emits + consumes; AI confirms | Queues/manifests are deterministic data. Confirmation is external input merged back, never runtime AI judgment. |
| Determinism is a product invariant | Atomic writes, `sort_keys`, no timestamps/randomness, stable cross-platform ordering. New DOCX/zip writers (none planned) would route through `normalize_docx_zip_timestamps`. |
| Provenance is metadata, never identity | Content-hash `<stem>-<kind>-<sha8>.md` stays the single identity. Relative folder path is a signal, not a key. |

---

## Artifact map (where every new file lives, and why)

Harness-emitted artifacts split by lifecycle owner. `context/` is deliberately
avoided for new writers (its `is_context_content_filename` skip-rules are a known
foot-gun); ingest artifacts live under `inbox/`, build artifacts under `sections/`.

| Artifact | Path | Owner | Rationale |
|----------|------|-------|-----------|
| Recursive-ingest report | `inbox/_detection.json` (extended) | `IngestService` | Already exists; extend fields, keep `_`-prefix skip. |
| Source manifest (roles/dupes/provenance) | `inbox/_source-manifest.json` | `IngestService` | Ingest-time; distinct from collection's `sections/source-manifest.json`. |
| Role-classification queue | `inbox/_classification-queue.json` | `IngestService` | Pending agent confirmation. |
| Placement queue (verbatim assets) | `inbox/_placement-queue.json` | asset routing step | Pending agent confirmation. |
| Figure catalog | `sections/figure-catalog.json` | ingest/asset step | Referenceable by sections at build time. |
| Gap report | `sections/gap-report.json` | `ContextService` | Sits with section contracts; agent-readable. |
| Template skeleton | `<template>.json` (stdout/file) | `template init` | New CLI surface. |

`_`-prefixed under `inbox/` is skipped by both `IngestService.ingest_inbox` and
`OpendataloaderPdfAdapter._discover_candidates` (existing rule) — so every new
inbox artifact is automatically invisible to the source walk. This is the
reason inbox artifacts are `_`-prefixed and build artifacts are not.

---

## Decision 1 — Template-as-schema enforcement

**Committed:** convert the 6 hardcoded `_check_*` in `rules.py` into
conditional/consistency checks; add a **separate** `validate_template` domain
function for `template validate`; evacuate Spanish literals to template data.

### 1a. `rules.py` check conversions

| Check | Today | After |
|-------|-------|-------|
| `_check_apa7_enabled` | `apa7.enabled` must be `True` unconditionally | **Deleted.** `review_apa7_text` already no-ops when `apa7.enabled` is false — the gate is sufficient. |
| `_check_extracted_dir_policy` | `extracted_dir_policy == "rules_traceability_only"` even when absent | Fires **only if** `paths.extracted_dir` is set (mirrors `doctor.py:38`); validates the policy value is consistent, `required=False` parity. |
| `_check_source_priority_excludes_extracted` | literal `"docs/extracted"` compared | Fires only if `paths.extracted_dir` set; compares against the template's **own** `extracted_dir` value, not a literal. |
| `_check_preliminaries_pagination` | roman must be enabled; intro must == `"introduccion"` | Fires only if `preliminaries` present; checks `body_pagination_start.section_id` **references an existing section** (`template.sections`/`structure`), not a literal name; roman check only if the roman block is declared. |
| `_check_margins_and_cover_policy` | keys must == `2.5`; cover must == `preserve_template` | Fires only if `format.page_margins_cm.non_cover` present; validates the four keys are **numeric cm values** (delete `_EXPECTED_MARGIN_CM`); cover check only if `cover_policy` declared. |
| `_check_margin_advisor_override_active` | requires literal id `margins-2-5cm-non-cover` active | **Deleted.** Couples a generic mechanism to one literal id; the margin check already validates the contract. |

Keep unchanged (structural, not document-type-specific): `_check_manifest_state`,
`_check_missing_section_contracts`, `_check_section_contracts_content`.

**Alternatives considered:** (2) separate AI-authored `document-schema.json` and
(3) rules-as-data DSL — both rejected in `explore.md`: they add an unvalidated
translation/interpretation hop, the exact "trust AI blindly" surface this repo
already avoids. Every hardcoded check is a fixed-shape structural comparison, so
conditional Python functions with docstring-as-spec-citation are the right grain.

**Test seam:** `tests/unit/domain/test_rules.py` — new baseline builders
`_generic_extra()` (no preliminaries/margins/extracted) proving each converted
check **stays silent when its block is absent**, plus `_estadia_extra()`
(current `_valid_extra()` contents) proving each check **still fires identically**
when the block is present. The ~15 `_valid_extra()`-dependent tests are rewritten
against these two, not extended.

### 1b. `template validate` — completeness without strictness

`Template(extra="allow")` **must not** become a strict model — open extension is
a contract. Completeness is enforced by a new pure domain function:

```
domain/template_validation.py
  validate_template(raw: dict) -> list[Issue]
```

It checks: required top-level blocks present (`type`, `title`, `sections`,
`section_contracts`, `context_schema`); every `sections[].id` has a matching
`section_contracts` entry; every `context_schema.topics[].id` is unique; declared
blocks are internally consistent (e.g. a `body_pagination_start.section_id` that
names a real section). It reuses `_check_missing_section_contracts` logic. It
**does not** reject unknown keys. Returns machine-readable `Issue`s.

**Alternative considered:** a second strict pydantic model mirroring `Template`.
Rejected — it duplicates the model and drifts from what `rules.py` enforces. A
validation *function* over the raw dict is the single source of completeness truth.

**Test seam:** `tests/unit/domain/test_template_validation.py` — incomplete
skeleton rejected; `reporte-estadia-tic.json` and `documento-generico.json`
accepted; unknown extension keys tolerated.

### 1c. `template init` skeleton

`template init <type>` emits a documented JSON skeleton with **every block
present**. JSON has no comments, so inline documentation and completeness markers
use two conventions that survive `extra="allow"` and are machine-checkable:

- `"$comment"` sibling keys (JSON-Schema convention) carry human guidance; ignored
  by pydantic, strippable, never enforced.
- Required-to-fill leaf values are emitted as **explicit sentinels** (`null` or
  `"TODO"`), which `validate_template` treats as "incomplete". Completeness is thus
  machine-checkable: `template validate` on a fresh skeleton reports every TODO.

**Test seam:** `tests/integration/test_template_cli.py` — `init` output parses as
`Template`; every declared block present; `validate` on fresh `init` output
reports the expected incomplete markers; filling them makes `validate` pass.

### 1d. Normative-defaults evacuation (#9)

Move the Spanish-thesis lexicons out of `domain/normative.py` module constants:

| Constant | Fate |
|----------|------|
| `EXCLUDED_FRONT_MATTER`, `FIRST_PERSON_PATTERNS`, `SUBJECTIVE_TERMS` | Evacuated. `resolve_normative_settings` defaults become **empty**; templates must declare them. |
| `SECRET_PATTERNS` | **Kept** — language-neutral security default, not document-type policy. |

Backward compat for `reporte-estadia-tic` is preserved by **backfilling** these
now-explicit blocks into `reporte-estadia-tic.json` (and the `template init`
Spanish-thesis example) so runtime behavior is byte-identical while no Spanish
literal remains in domain code.

**Test seam:** characterization test first (below, Decision 10) captures current
`review_section_text` output for estadía inputs; the backfilled template must
reproduce it byte-for-byte. Plus a structural guard (Decision 10).

---

## Decision 2 — Recursive ingest

**Committed:** `rglob`-based recursive walk, POSIX-normalized relative-path
provenance, `inbox/assets/` excluded, loud reporting of everything ignored.

- **Traversal:** replace `inbox_dir.iterdir()` with a recursive walk. Use manual
  `sorted()` over `rglob("*")` results filtered to files, so ordering is under our
  control (not OS `rglob` yield order). Skip any path whose **any** component
  starts with `_` (extends the existing top-level `_`-prefix rule to the tree) and
  any path under `inbox/assets/` (verbatim-asset subtree, Decision 6).
- **Deterministic ordering:** sort by the POSIX relative path string
  (`path.relative_to(inbox_dir).as_posix()`), case-sensitive, so Windows and Linux
  produce identical order. This is the single ordering key for report + manifest.
- **Provenance field:** each report/manifest entry gains
  `"relative_path"` (POSIX, relative to `inbox/`) and `"source_dir"` (its parent,
  `""` for root). Identity (`<stem>-<kind>-<sha8>.md`) is **unchanged** — folder is
  a signal only.
- **Collision semantics:** equal stems in different subfolders already
  disambiguate via content hash. Report shape surfaces this explicitly: entries
  carry `relative_path`, so two `readme.md` in different folders are two distinct
  rows even if they collapse to the same output when byte-identical (then the
  second is `status: "batched"`/`"skipped"` per Decision 3, with both
  `relative_path`s recorded).
- **Empty directories:** directories that yield no ingestable file are reported
  as `{"relative_path": "<dir>/", "status": "empty_dir"}` — never silent.
- **Unsupported/ignored:** existing `status: "unsupported"` retained; skipped
  `_`-prefixed and `assets/` items are **not** reported as errors but summarized in
  a new report field `"ignored": [...]` so nothing disappears silently.

**Alternative considered:** `os.walk` with manual stack — equivalent, but `rglob`
+ explicit sort is fewer lines and the sort key (not the walker) owns determinism.

**Test seam:** `tests/unit/application/test_ingest_service.py` +
`tests/integration/test_ingest_recursive.py` — nested tree with equal stems,
empty dir, `_`-prefixed file, `assets/` subtree; assert report ordering is
byte-stable across two runs and identical field set.

---

## Decision 3 — JVM look-ahead batching under recursion

**Committed:** per-directory batching + a pre-scan output snapshot that yields a
precise 3-way status vocabulary.

- **Batching scope:** per-directory (proposal's lean). The adapter's
  `_discover_candidates` already batches siblings in `seed_src.parent` — under
  recursion this naturally means "same directory", which keeps the
  "skipped-because-batched" story locally explainable. **No change to batch
  scope.** Whole-tree batching is rejected: it would make one directory's failure
  contaminate unrelated siblings and break the per-directory provenance story.
- **Status vocabulary (the real fix for #12):** `IngestService` snapshots the set
  of existing `ingested/` output paths **once, before any conversion** this scan.
  Per file, status resolves against that snapshot:

  | Status | Meaning |
  |--------|---------|
  | `ingested` | Converted this run; output written by *this file's* handler call. |
  | `batched` | Converted this run inside a sibling's look-ahead batch (output absent from the pre-scan snapshot but present when reached). **New status — resolves #12.** |
  | `skipped` | Output was present in the pre-scan snapshot — genuinely idempotent from a prior run. |
  | `unsupported` / `error` | Unchanged. |

  This lives entirely in `IngestService` (snapshot + comparison) — **no port
  change**, the adapter stays batch-internal. Existing consumers that only read
  `ingested`/`skipped`/`error` still work; `batched` is additive.

**Alternative considered:** expose `converted_this_run` from the PDF adapter so
`IngestService` can ask it. Rejected — only the PDF handler batches; a per-handler
introspection method leaks a single adapter's concern into the port. The
output-snapshot approach is handler-agnostic and works for any future batching
adapter.

**Test seam:** `tests/integration/test_ingest_recursive.py` with a fake PDF
handler that finalizes siblings eagerly — assert first sibling `ingested`, second
`batched`, and a re-run reports both `skipped`.

---

## Decision 4 — Source-role classification

**Committed:** deterministic folder-lexicon + filename-pattern signals produce a
proposed role + confidence into a confirmation queue; confirmed role gates
downstream use.

- **Signal set (deterministic, no content AI):**
  - Folder-name lexicon (case-folded, on any relative-path component):
    `normative` <- {normativa, norma, reglas, rules, manual, lineamientos};
    `example` <- {ejemplo, ejemplos, muestra, sample, reference, referencia, plantilla};
    `evidence` <- {evidencia, evidence, anexos, sources, fuentes, capturas}.
  - Filename patterns (secondary, lower weight): same lexicon on the stem.
  - **No content probes in the first cut** — kept deterministic and cheap; content
    probing is a documented future extension, not this change.
- **Confidence:** a deterministic score, `min(1.0, 0.5*folder_hit + 0.3*name_hit)`
  style bucketed to `{high, medium, low}` — pure function of signal counts, no
  floats persisted beyond a fixed rounding. Unmatched -> role `unknown`,
  confidence `low`.
- **Queue file:** `inbox/_classification-queue.json`, deterministic writer
  (atomic, `sort_keys`), entries keyed by `relative_path` with
  `{proposed_role, confidence, signals[]}`. The agent (external) edits/confirms;
  confirmation is merged back into `inbox/_source-manifest.json` under
  `confirmed_role`.
- **Gating downstream use:** a confirmed role routes the source:
  `normative` -> normative-rules input (`manual_dir` family);
  `example` -> style reference (never a content source);
  `evidence` -> collect-sources / evidence pipeline.
  **Default when unconfirmed:** in **draft** the source is admitted with its
  *proposed* role and a `PENDIENTE`-style gap entry; in **strict** an unconfirmed
  role **blocks** (consistent with the draft/strict split, Decision 7).

**Alternative considered:** classify by MIME/kind only. Rejected — kind
(pdf/docx/md) is orthogonal to role (a PDF can be normative, example, or
evidence); folder intent is the deterministic signal that actually carries role.

**Test seam:** `tests/unit/domain/test_source_role.py` — pure classifier over
crafted relative paths (each lexicon bucket, mixed, none); queue writer
determinism test (two runs byte-identical); gating test in service layer
(unconfirmed blocks in strict, admits in draft).

---

## Decision 5 — Near-duplicate detection

**Committed:** normalized-word k-shingle + Jaccard with a fixed threshold, run
after ingest on the produced Markdown, highest-fidelity kept, decision recorded
reversibly.

- **Algorithm (deterministic):** for each ingested `.md`, normalize text
  (reuse `markdown_text.clean_markdown_text` + lowercase + collapse whitespace),
  build the set of overlapping **5-word shingles**, compute pairwise Jaccard.
  Fixed threshold `>= 0.85` marks a near-duplicate pair. Pure set math -> fully
  deterministic, no randomness (simhash rejected below).
- **Where it runs:** a post-ingest pass in `IngestService` over the just-produced
  `ingested/` outputs (their content is stable and already deterministic), so it
  sees final normalized artifacts, not raw heterogeneous sources.
- **Fidelity ranking (kept-vs-superseded):** fixed order
  `curated_md > docx_converted_md > pdf_extracted_md > txt_md`, derived from the
  source `kind` recorded at ingest. Tie-break by POSIX `relative_path` (stable).
  The higher-fidelity member is `kept`; the other is `superseded` (not deleted).
- **Manifest record (reversible):** in `inbox/_source-manifest.json`,
  `duplicates: [{kept, superseded, jaccard, reason}]`. Nothing is removed from
  disk — superseded outputs stay, only their downstream *use* is suppressed, so a
  human can reverse the decision by editing the manifest.

**Alternative considered:** simhash / MinHash. Rejected for the first cut —
MinHash needs seeded hash permutations (a determinism-seeding surface), and at
this corpus size exact Jaccard over shingles is cheap and needs zero seeds. Simhash
is a future optimization if corpus size ever demands it.

**Test seam:** `tests/unit/domain/test_near_duplicate.py` — identical, near
(one edit), and disjoint texts; assert threshold boundary; assert fidelity
ranking picks the curated over the pdf-extracted regardless of input order.

---

## Decision 6 — Verbatim assets + figure catalog

**Committed:** an `inbox/assets/` convention + heuristic routing runs **before**
the source walk; placement lands in a queue then in `structure` parts; figure
catalog dimensions come from python-docx's bundled image parser (no new dep).

### 6a. Pre-ingest routing (order)

Pipeline order becomes: **(1) asset-routing step -> (2) recursive source walk ->
(3) ingest -> (4) near-dup -> (5) classification queue**. Step 1 moves declared
verbatim assets out of the flatten path so they never reach markdown handlers.

- **`inbox/assets/` subtree:** anything here is a declared verbatim asset,
  excluded from the source walk (Decision 2), routed to `assets/`.
- **Heuristic detection outside `inbox/assets/`:** files whose kind is an image
  (`.png/.jpg/.jpeg/.gif/.tiff/.bmp`) or a `.docx` in a folder named like
  `portada/cover/anexo-visual` are *proposed* as verbatim assets. Proposals go to
  the placement queue — they are **not** auto-routed (avoids stealing a legitimate
  `.docx` content source).
- **Placement queue:** `inbox/_placement-queue.json`, entries
  `{relative_path, proposed_kind: cover|front|back, proposed_part: cover_from_asset|embed_docx}`.
- **Confirmation lands twice:** confirmed placements are written into the
  document `structure` as `cover_from_asset`/`embed_docx` parts (already supported
  by `docx_structure.structure_parts` and validated by `doctor.py:55-66`) **and**
  recorded in a `placements` block of `inbox/_source-manifest.json` for audit.

### 6b. Figure catalog

- **Dimensions without a new dep:** `python-docx` (already a dependency) bundles a
  PIL-free image header parser (`docx.image`) that reads px width/height/dpi for
  PNG/JPEG/GIF/BMP/TIFF. A new **`ImageMetadataPort`** with a python-docx-backed
  adapter reads dimensions. If a format is unparseable, dimensions are recorded as
  `null` — **never guessed** (determinism preserved). No Pillow.
- **Catalog shape:** `sections/figure-catalog.json`,
  `{figures: [{id, sha256, width_px, height_px, origin_relative_path, caption}]}`
  where `id` is a stable hash-derived token (`fig-<sha8>`), sorted by `id`.
- **Deterministic section references:** sections reference a figure by its stable
  `id`; the catalog is the lookup table so the AI knows which figures exist and
  the build resolves references without wall-clock or ordering ambiguity.

**Alternative considered:** add Pillow for richer metadata. Rejected — violates
"no new heavyweight runtime dep"; python-docx's parser covers every dimension we
need and is already installed.

**Test seam:** `tests/unit/domain/test_figure_catalog.py` (pure catalog builder
given metadata tuples, stable ordering) + `tests/integration/test_image_metadata_adapter.py`
(real png/jpg dimensions; unparseable -> `null`, no raise).

---

## Decision 7 — Gap report

**Committed:** a machine-readable JSON gap report combining context required-fields
and section `required_content`, wired into the existing draft/strict split.

- **Sources of gaps:**
  1. Context: reuse `ContextService.status` + `domain/context.missing_fields`
     (already built) for missing required topics/fields.
  2. Sections: a **new** domain function over `required_content` reusing
     `rules.requirement_present` against current section bodies, surfaced
     *pre-emptively* (today it only fires at review time).
- **Format + location:** `sections/gap-report.json`,
  `{schema: 1, context_gaps: [...], section_gaps: [...]}` — stable key order,
  atomic write, no timestamps. Deliberately **not** under `context/` (avoids the
  `is_context_content_filename` entanglement).
- **Draft/strict wiring:** the report is always emitted. Behavior keys off the
  resolved `strict_policy` block: in **draft**, gaps are advisory and the pipeline
  proceeds with `PENDIENTE` markers (existing `allow_pending` path); in **strict**,
  a non-empty gap report **blocks** the pipeline with the report as the failure
  payload. This reuses the existing strict severity mechanism, adding no new
  policy surface.

**Alternative considered:** extend the existing `_requests.md` questionnaire only.
Rejected as insufficient — `_requests.md` covers context topics but not section
`required_content`; the JSON gap report is the machine-readable superset an agent
consumes before a full pipeline run.

**Test seam:** `tests/unit/application/test_context_gap_report.py` — missing
context field + missing section content both appear; empty when complete;
`tests/integration/test_pipeline_strict_gap.py` — strict blocks on gaps, draft
proceeds.

---

## Decision 8 — Workspace / bootstrap fixes

**Committed:**

- **`doc new` creates `inbox/` + `inbox/assets/`** (#10): add both to
  `documents.py:_SUBDIRS`. Purely additive; no existing doc affected.
- **Orphan `_media/` cleanup (#13):** runs as a step during the ingest scan.
  **Only content-addressed orphans** are removed — a file under `_media/` is
  deleted **only if** its name matches the content-addressed pattern **and** no
  current ingested output references it. Anything not matching the
  content-addressed shape is **refused** (left in place, reported in
  `_detection.json.ignored`), so the cleanup can never delete a human's file.
- **`build-rules` absent-path handling (#8):** `EvidenceService.build_rules`
  guards `manual_dir`/`extracted_dir` with `.get()` (matching `rules_hash` at
  line 121) and **skips** absent dirs rather than raising `KeyError`.
  **Decision: skip-with-loud-report** — a missing optional path is reported as a
  skipped input in the manifest, not a degraded silent run and not a hard failure.

**Test seam:** `tests/unit/application/test_documents.py` (inbox dirs created);
`tests/unit/application/test_media_cleanup.py` (content-addressed orphan removed,
foreign file refused); `tests/integration/test_evidence_service.py`
(`documento-generico` `build-rules` succeeds with empty `paths`).

> Clarification (fresh-context verify, PR2 fix batch, WARNING-2): the
> implementation reports refused items under
> `report["media_cleanup"]["refused"]` (a list of `{path, cause}` entries),
> not a top-level `_detection.json.ignored` field as this decision's prose
> literally says. Substance is unchanged (refused items are always written
> into `_detection.json`, never silently dropped) -- only the field's name
> and location differ. Reason: Front C (Phase 7, not yet implemented) is
> expected to introduce its own shared top-level `ignored` field for skipped
> `_`-prefixed/`assets/` items during the recursive walk (Decision 2);
> keeping media-cleanup refusals scoped under their own `media_cleanup` key
> avoids pre-empting that shape with a generically-named field only to
> reconcile the two later. `refused` also grew richer semantics than a bare
> `ignored` list would carry cleanly: each entry now needs a `cause` (shape
> mismatch, unexpected content, or a filesystem error), used for the
> WARNING-1/SUGGESTION-1 hardening in the same PR2 fix batch. Front C's own
> apply-progress should explicitly reconcile (or deliberately keep separate)
> its `ignored` field against this one when that front lands.

---

## Decision 9 — Layering (ports, adapters, wiring)

Every new artifact = **pure domain builder** + (if it does I/O) a **port** +
**adapter**, wired only in `cli/_shared.py`.

| Concern | Domain (pure) | Port | Adapter | Wiring |
|---------|---------------|------|---------|--------|
| Check conversions | `rules.py` (edit) | — | — | none |
| Template validation | `template_validation.validate_template` | — | — | none |
| Source-role classify | `source_role.classify(relative_path)` | — | — | none |
| Near-dup detect | `near_duplicate.find_duplicates(docs)` | — | — | none |
| Figure catalog build | `figure_catalog.build(entries)` | `ImageMetadataPort` | `PythonDocxImageMetadataAdapter` | `Deps.__init__` |
| Gap report build | `context.build_gap_report(...)` | reuse `ContextRepository` | — | none |
| Deterministic JSON artifacts (report/manifest/queues/catalog) | builders return dicts | **`IngestArtifactWriter`** (new, atomic+sorted) | `FilesystemIngestArtifactWriter` | `Deps.__init__` -> `IngestService` |

- **New ports (2):** `ImageMetadataPort` (image dims), `IngestArtifactWriter`
  (atomic deterministic JSON writer). The writer replaces `IngestService`'s
  current inline `_write_detection_report` `write_text` call, so **all** inbox
  artifacts go through one atomic, testable seam (fake writer in unit tests).
- **Changed ports:** none of the existing port *signatures* change.
  `SourceIngestPort.ingest(src, out_dir, kind)` is untouched — the batching status
  fix is `IngestService`-internal (Decision 3).
- **Composition-root wiring:** `Deps.__init__` gains the two new adapters and
  passes them to `IngestService`; `ContextService` gains no new dependency (gap
  report reuses `ContextRepository`).
- **Dependency direction preserved:** domain builders import nothing from
  application/infrastructure; adapters implement domain ports; the AI is never
  called at runtime — queues are data.

---

## Decision 10 — Migration / compatibility

**Committed:** characterization-first, guard-test-enforced, baseline-rewrite plan.

1. **`reporte-estadia-tic.json` byte-behavior-identical proof:** before touching
   `rules.py`/`normative.py`, add characterization tests that snapshot the current
   `review_rules` + `review_section_text` output for the estadía template and a
   representative section corpus. The refactor must reproduce these outputs
   exactly. Normative-lexicon backfill (Decision 1d) is validated by these same
   snapshots.
2. **Structural "no estadía literal" guard** (house precedent
   `test_module_source_has_no_tesina_literal`): a new
   `test_no_document_type_literal_in_domain` scans `rules.py` + `normative.py`
   source for the banished literals — `"introduccion"`, `_EXPECTED_MARGIN_CM`/`2.5`,
   `"margins-2-5cm-non-cover"`, `"docs/extracted"`, `"rules_traceability_only"`,
   `"manual-estadia-tic"`, and the Spanish first-person/subjective lexicons. This
   is the enforcement that prevents regression to hardcoding.
3. **`build_manifest` `normative_source` (#7):** becomes a parameter sourced from
   the template (`normative.normative_source`, default `""`), removing the literal
   from `domain/evidence.py`.
4. **`_valid_extra()` baseline rewrite:** split into `_generic_extra()` and
   `_estadia_extra()` (Decision 1a). Each of the ~15 dependent tests moves to the
   baseline that matches its intent; new "stays silent when block absent" tests are
   added per converted check. This is the real migration cost and is scheduled
   **first** within the policy-de-hardcoding front so the suite stays green as
   production code changes.

**Test seam:** `tests/unit/domain/test_rules_characterization.py` (snapshots),
`tests/unit/test_no_document_type_literal.py` (structural guard).

---

## Risk register (updates to proposal risks)

| Risk | Likelihood | Design mitigation |
|------|------------|-------------------|
| `reporte-estadia-tic` regression | High | Characterization snapshots **before** refactor (Decision 10.1); lexicon backfill validated against them. |
| Test-suite blast radius (~923, strict TDD) | Medium | `_valid_extra()` split scheduled first (10.4); front-by-front slicing. |
| `batched` status breaks existing consumers | Low | Additive value; existing readers only match `ingested`/`skipped`/`error` (Decision 3). |
| Determinism regression from new writers | Medium | Single `IngestArtifactWriter` atomic+`sort_keys` seam (Decision 9); catalog dims `null` never guessed. |
| Cross-platform ordering drift under recursion | Medium | Single POSIX `relative_path` sort key owns ordering, not OS walk order (Decision 2). |
| python-docx image parser lacks a format | Low | Dimensions -> `null`, never raise, never guess (Decision 6b). |
| Heuristic asset routing steals a content `.docx` | Medium | Outside `inbox/assets/`, detection only **proposes** to the placement queue; never auto-routes (Decision 6a). |
| AI-authored template/queue trusted blindly | Medium | `template validate` before use; queues are confirmed data merged back, no runtime AI (Decisions 1b, 4). |

## Suggested slicing sketch (fronts only — sdd-tasks owns boundaries)

Independent, mostly additive fronts. Delivery strategy is **ask-on-risk**; final
PR boundaries and chain shape are decided in sdd-tasks, not here.

| Front | Scope | Depends on |
|-------|-------|------------|
| **A. Policy de-hardcoding** | `rules.py` conversions, `evidence.py` #7, `build-rules` #8 guard, normative evacuation + `reporte-estadia-tic.json` backfill, `_valid_extra()` rewrite, characterization + guard tests | none (core, self-contained) |
| **B. Bootstrap** | `doc new` inbox dirs (#10), orphan `_media/` cleanup (#13) | none |
| **C. Recursive ingest** | recursive walk, provenance, loud reporting, `batched` status, `IngestArtifactWriter` | B (inbox exists) |
| **D. Source roles** | classifier + queue + manifest gating | C |
| **E. Near-duplicates** | shingle/Jaccard + fidelity ranking in manifest | C |
| **F. Verbatim assets + figures** | asset routing, placement queue, `ImageMetadataPort` + catalog | C |
| **G. Template lifecycle + gap report** | `template init`/`validate`, gap report + draft/strict wiring | A (validator shares check logic) |

Front A is the falsifiable core (`documento-generico` passes clean,
`reporte-estadia-tic` stays identical). C is the spine the ingest-family fronts
(D/E/F) build on. A and G share the validation logic but can ship independently.

## Checklist (design acceptance)

- [ ] Every hardcoded check #1-6 has a committed conditional/consistency form.
- [ ] `template validate` is a separate validator; `Template` stays `extra="allow"`.
- [ ] Normative Spanish literals leave domain code; estadía backfilled to its template.
- [ ] Recursive ingest ordering is a single POSIX key; provenance is metadata not identity.
- [ ] `batched` status resolves #12 with no port change.
- [ ] Roles/dupes/placements are deterministic queues/manifests, reversible, AI-confirmed.
- [ ] Figure dims via python-docx (no new dep); unparseable -> `null`.
- [ ] Gap report machine-readable; draft proceeds, strict blocks.
- [ ] Two new ports only (`ImageMetadataPort`, `IngestArtifactWriter`); no signature changes.
- [ ] Characterization + structural-literal guard tests scheduled first.

## Next step

`sdd-tasks` (after spec is ready) — turn these decisions into ordered, testable
tasks and commit the PR-chain boundaries the slicing sketch leaves open.
