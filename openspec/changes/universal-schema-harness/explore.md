# Exploration: universal-schema-harness

> Phase: explore | Status: complete | Artifact store: openspec
> Produced by sdd-explore (fresh-context investigation); persisted by orchestrator
> (sdd-explore agent toolset has no Write capability — content unmodified).

## Current State

The harness is hexagonal (domain → application → infrastructure, cli composition
root in `cli/_shared.py`). Its founding refactor (`universal-doc-harness`,
archived, 923 tests) made **rendering, pipeline stages, and asset-kind
validation** format-agnostic — but never touched **document-type policy**. Two
templates exist as fixtures only (no `templates/` dir in the repo; real
templates live at deploy time): `tests/fixtures/templates/documento-generico.json`
(apa7 disabled, no preliminaries/extracted_dir) and `reporte-estadia-tic.json`
(the legacy policy, fully declared as data).

The `Template` model (`src/docs/domain/models/template.py`) already has
`model_config = ConfigDict(extra="allow")` and typed blocks for `apa7`,
`strict_policy`, `context_schema`, `section_contracts`, plus an open `extra`
dict for `paths`, `normative`, `advisor_overrides`, `preliminaries`,
`cross_consistency`, `documents_tools`. A per-document `Document.overrides`
(`domain/models/document.py`) is deep-merged over the template at
`Deps.resolve_context()` (`cli/_shared.py:134-148`) — **the harness already has
a working "schema over template" mechanism**; the problem is that
`rules.py`/`doctor.py`/`evidence.py` don't consult it and instead hardcode one
document's expected values as universal law.

## Affected Areas — Full Hardcoding Inventory

| # | Location | What's hardcoded | Consequence |
|---|----------|-------------------|--------------|
| 1 | `src/docs/domain/rules.py:346-349` (`_check_apa7_enabled`) | `template.apa7.enabled` MUST be `True`, unconditionally | `documento-generico` (apa7 disabled by design) always fails `review-rules` |
| 2 | `src/docs/domain/rules.py:352-359` (`_check_preliminaries_pagination`) | `preliminaries.roman_pagination.enabled` MUST be `True`; `body_pagination_start.section_id` MUST literally equal `"introduccion"` | Any document without roman-numeral preliminaries, or whose intro section isn't named exactly `introduccion`, fails |
| 3 | `src/docs/domain/rules.py:332-336` (`_check_extracted_dir_policy`) | `paths.extracted_dir_policy` MUST literally equal `"rules_traceability_only"`, **even when `paths.extracted_dir` is absent** | Contradicts `doctor.py`'s own conditional version (only checks when `extracted_dir` is configured, `required=False`) — two mirrored checks disagree |
| 4 | `src/docs/domain/rules.py:339-343` (`_check_source_priority_excludes_extracted`) | Literal string `"docs/extracted"` compared against `project.source_priority` entries | Assumes one fixed extracted-dir location. (Note: earlier deficiency brief claimed a backslash literal here; verified against file bytes — the literal uses a forward slash. The hardcoding itself is the issue.) |
| 5 | `src/docs/domain/rules.py:362-378` (`_check_margins_and_cover_policy`) | `_EXPECTED_MARGIN_CM = 2.5` module constant; `cover_policy` MUST equal `"preserve_template"` | Any document with different margin conventions fails |
| 6 | `src/docs/domain/rules.py:381-387` (`_check_margin_advisor_override_active`) | Requires an `advisor_overrides` entry with `id == "margins-2-5cm-non-cover"` and `status == "active"` | Couples a generic "active overrides" mechanism to one literal ID string |
| 7 | `src/docs/domain/evidence.py:41` (`build_manifest`) | `"normative_source": "docs/guides/manual-estadia-tic"` literal in the returned manifest dict, not a parameter | Every generated `manual-rules.json` claims estadía-TIC as its normative source regardless of actual template |
| 8 | `src/docs/application/evidence.py:45-46` (`EvidenceService.build_rules`) | **New finding**: unconditional `Path(config["paths"]["manual_dir"])` / `Path(config["paths"]["extracted_dir"])` — no `.get()` guard, unlike every other path access in the same file (e.g. `rules_hash` at line 121 does guard) | `pipeline prep`'s `build-rules` stage raises `KeyError` for `documento-generico` (`paths: {}`) — caught by `run_pipeline`'s generic exception wrapper, but the stage always fails |
| 9 | `src/docs/domain/normative.py:6-41` | Module-level `EXCLUDED_FRONT_MATTER`, `FIRST_PERSON_PATTERNS`, `SUBJECTIVE_TERMS` (Spanish thesis-specific defaults) | Lower severity — defaults used via `.get()` when `config["normative"]` doesn't override them; already overridable data, just estadía-flavored fallbacks baked into domain code |
| 10 | `src/docs/application/documents.py:23-27` (`_SUBDIRS`) | `doc new` creates `corrections/inbox` but never `inbox/` (the source-ingest inbox) | `inbox_dir` is only ever a computed path string (`cli/_shared.py:205`), never `mkdir`'d — users must create it manually |
| 11 | `src/docs/application/ingest.py:41-45` (`IngestService.ingest_inbox`) | `inbox_dir.iterdir()` + `is_file()` — one level deep only | No recursive scan; subfolders silently invisible, no report entry at all |
| 12 | `src/docs/infrastructure/ingest/opendataloader_pdf_adapter.py:22-35` | JVM look-ahead batches ALL sibling `.pdf` files in one `convert()` call per scan | Sibling PDFs converted in the same batch report `status: "skipped"` even on their very first run — misleading semantics inherited from a real architectural constraint (JVM spin-up cost) |
| 13 | Test suite anchoring: `tests/unit/domain/test_rules.py:420-435` `_valid_extra()` | Encodes the **entire estadía-TIC policy** (extracted_dir_policy, source_priority, roman preliminaries, margins, advisor override) as the "valid" baseline reused by ~15 `review_rules`/`_check_*` tests | These tests must be rewritten, not just the production code — real migration cost lives here |

Sections `sections/ingested/`, asset flow (`asset.py`, `docx_structure.py`),
pipeline stage sets (`domain/pipeline.py`), and context-curation
(`application/context_files.py`, `context.py`) were also inspected and are
**already correctly data-driven / format-agnostic**. `CONCERNS` (the 5 fixed
context-curation topics) is a fixed vocabulary contracted by the
`context-curation` spec's Purpose statement, not an accidental leak — optional
future extension only.

## Approaches

### 1. Extend the existing `Template` as the single universal schema, made strict and declarative

- Convert every hardcoded `_check_*` in `rules.py` into a **conditional,
  template-declared** check: `_check_apa7_enabled` is deleted (the
  `Apa7Config.enabled` gate that `review_apa7_text` already respects is
  sufficient); `_check_preliminaries_pagination` only runs — and only compares
  against the template's own declared `structure`/`body_restart_section` — if
  `preliminaries` is present, checking internal *consistency* rather than a
  hardcoded expected value; `_check_extracted_dir_policy` only fires if
  `paths.extracted_dir` is configured (mirroring `doctor.py`'s existing
  conditional pattern); margins/advisor-override checks become "if a
  `page_margins_cm.non_cover` block exists, its four keys must be numeric cm
  values" instead of "must equal 2.5".
- **Pros**: Reuses the model/override mechanism that already works
  (`Document.overrides` deep-merge); zero new artifact types; smallest
  migration since two working fixtures already demonstrate the intended shape;
  the two existing templates become the acceptance tests (`documento-generico`
  must pass `doctor`/`review-rules` clean, `reporte-estadia-tic` must keep
  passing exactly as today).
- **Cons**: `rules.py`'s ~15 direct unit tests need rewriting, not just
  extension; requires care to keep `reporte-estadia-tic.json` behaviorally
  identical (regression risk against the one real, working document type).
- **Effort**: Medium (single module + its evidence.py/doctor.py callers + their
  direct tests; ports/architecture unchanged).

### 2. Separate AI-generated "document-type schema" artifact, distinct from Template

- A new top-level schema file (e.g. `document-schema.json`) generated by the AI
  agent into the workspace, validated via a strict pydantic/JSON-Schema model,
  from which `Template`, `rules.py` checks, and `context_schema` are *derived*
  at load time.
- **Pros**: Cleanly separates "what the AI decided this document needs" from
  "how the harness executes it"; could support richer AI-authored intent beyond
  what `Template.extra` can hold.
- **Cons**: Duplicates most of what `Template` + `Document.overrides` already
  do; requires a new port, a new validation layer, new composition-root wiring,
  and a translation step from schema → Template — significant new surface for a
  problem the existing model already addresses; higher risk of the AI's schema
  drifting out of sync with what `rules.py` actually enforces (violates
  "harness must never blindly trust AI output" more, not less, by adding an
  unvalidated translation hop).
- **Effort**: High.

### 3. Rules-as-data DSL interpreted by a generic rule engine

- Replace the ~10 `_check_*` Python functions with a declarative list of rule
  descriptors (e.g. `{"path": "apa7.enabled", "op": "eq", "value": true}`)
  stored in the template and interpreted by one generic evaluator.
- **Pros**: Maximum flexibility — a document-type could declare arbitrary new
  checks without touching Python, closest to "zero hardcoded policy" literally.
- **Cons**: A generic rule DSL is itself a small programming language the
  harness must validate and sandbox (determinism + "never trust AI blindly"
  risk goes up, since rule *logic itself* becomes AI-authored data, not just
  rule *parameters*); over-engineered relative to the actual need — every
  hardcoded check today is a fixed-shape structural comparison
  (equality/presence), not arbitrary logic; loses the descriptive
  docstrings-as-spec-citations pattern the codebase relies on for auditability.
- **Effort**: High.

## Recommendation

**Approach 1** (extend `Template` as the universal schema). The architecture
already built the right mechanism — `extra="allow"` + `Document.overrides`
deep-merge — during the founding refactor; the bug is that
`rules.py`/`doctor.py`/`evidence.py` treat one document's declared policy as
universal instead of reading it from the resolved config. This is a targeted,
well-bounded fix rather than a new subsystem, and directly falsifiable: the
acceptance criterion is "`documento-generico` passes
`doctor`/`review-rules`/`build-rules` cleanly with zero errors, and
`reporte-estadia-tic` continues to pass with byte-identical behavior."
Approaches 2 and 3 solve a problem the codebase doesn't have yet
(`Template.extra="allow"` already accepts arbitrary AI-declared policy) while
adding real new validation/trust surface.

### Recursive ingest

Extend `IngestService.ingest_inbox` to walk recursively (`rglob` / manual
stack, not `iterdir`), capture each file's relative path (folder-name signal)
into the `_detection.json` report and into a new source-manifest field (the
flat `<stem>-<kind>-<sha8>.md` naming in `ingest_naming.py` stays unchanged —
collision-safe already since identity is content-hash-based, not path-based),
and explicitly report ignored directories/unsupported items (never silent).
The opendataloader-pdf JVM look-ahead batching is a real constraint —
recursive scan must decide (and document) whether look-ahead batches
per-directory or across the whole tree; recommend per-directory to keep the
"skipped-because-batched" semantics locally explainable rather than global.

### Verbatim-asset declaration

Closest fit is a sidecar manifest convention (e.g. `inbox/_assets.json` or a
per-file marker) that the AI/user populates to say "this file goes to
`assets/` as `cover_from_asset`/`embed_docx`, placement: front|back|cover",
processed as a **pre-step before ingest** (so a declared verbatim asset never
reaches the markdown-flattening handlers at all). The `AssetService`/`asset
add` flow and `cover_from_asset`/`embed_docx` structure-part types already
work end-to-end — the gap is purely "inbox → assets/ routing decision," not
the embed mechanism itself.

### Gap-detection/elicitation

Already 80% built: `ContextService.status`/`missing_fields`
(`domain/context.py`) + `write_requests_file` (renders a pending-fields
questionnaire) is the exact "machine-readable gap report → agent turns into
questions" flow requested. Extend it to also surface
`SectionContract.required_content` gaps (today only checked at review-time via
`requirement_present`, not exposed as a pre-emptive gap report) so the AI can
ask about missing section content, not just missing context topics, before
running a full pipeline.

## Risks

- **Regression on the one real working document type (High)**:
  `reporte-estadia-tic.json` is the only template with production users; every
  `rules.py` change must be proven byte-behavior-identical against it (the
  founding refactor's own precedent — `test_module_source_has_no_tesina_literal`
  — shows this codebase already tests "no hardcoded literal" as a structural
  invariant; expect a parallel estadía-literal guard).
- **Frozen specs delta scope (Low-Medium)**: none of the 5
  `openspec/specs/*/spec.md` capabilities mention APA/estadía/preliminaries/
  margins as contract requirements — the hardcoding is pure implementation
  drift, so this change deltas cleanly against `document-pipeline` without
  contradicting frozen scenarios. Recursive ingest and verbatim-asset routing
  DO need new/modified requirements in `document-ingest` and
  `asset-management` respectively.
- **Test suite blast radius (Medium)**: ~923 tests, strict TDD mandatory;
  `test_rules.py`'s `_valid_extra()` baseline (~15 dependent tests),
  `test_doctor_service.py`, `test_cli_collection.py`, `test_pipeline_service.py`
  all assert current hardcoded behavior and need rewriting alongside the fix.
- **Determinism gotchas (Low, well-documented)**: any new inbox-manifest/
  sidecar writer must follow the no-timestamps/no-randomness discipline and
  MUST reuse `context_index_files.py:is_context_content_filename` conventions
  if it touches `context/`; `ingest_naming.py`'s content-hash identity must
  stay the single source of truth even as recursive paths add a "relative
  folder" provenance signal (folder path is provenance metadata, not identity).
- **JVM batching semantics (Medium)**: recursive ingest changes the definition
  of "sibling" for opendataloader-pdf's look-ahead batching — needs an explicit
  design decision (per-directory vs. whole-tree), not an incidental side effect.
- **`application/evidence.py:45-46` unconditional KeyError (Medium, newly
  found)**: must be fixed as part of the same change or `documento-generico`-
  style templates keep failing `build-rules` even after `rules.py` is fixed —
  a second, independent blocker on the same user journey.

## Ready for Proposal

Yes. Scope is well-bounded: primarily `rules.py` + two thin
`evidence.py`/`doctor.py` call sites for the policy-hardcoding front,
`ingest.py` + reporting for recursion, a new sidecar convention for verbatim
assets, and an extension to the existing `ContextService` gap-reporting for
elicitation. Open product fork to resolve before propose: verbatim-asset
declaration as sidecar manifest (`_assets.json`) vs. dedicated `inbox/assets/`
subfolder convention.
