# Design — `build-sections` (closing the last migration gap)

- **Date:** 2026-07-04
- **Status:** Approved (design phase)
- **Target project:** `docs/` (uv-managed Python project)
- **Source:** `old-se-debe-migrar/tesina/harness/scripts/tesina_harness.py` (legacy monolith)
- **Precedes:** implementation plan `docs/plans/2026-07-04-slice-17-build-sections.md` (via `superpowers:writing-plans`)
- **Follows:** `docs/plans/2026-07-02-slice-16-tech-debt-remediation.md` (technical-debt remediation, complete)

## 1. Context & Problem

Slices 1–15 migrated `tesina_harness.py` to a hexagonal `docs/` CLI, with one
deliberate, explicitly-documented gap: `build-sections` (the pipeline stage
that renders each section's initial draft and stamps it with content hashes)
was left unimplemented three times in a row (Slice 6, Slice 8, Slice 14's
Judgment call 3, reconfirmed in Slice 15) because it appeared to require "a
draft renderer plus a `prompts_dir`-scoped prompt-hashing concept this
migration has never modeled."

A technical-debt audit of the completed migration (2026-07-03) recommended
closing this gap in its own slice, starting from `superpowers:brainstorming`
rather than folding it into the remediation slice (16) that closed the
audit's other 5 findings. Slice 16 is complete; this is that follow-up.

Reading the legacy code directly (rather than re-trusting the "unmodeled"
label three prior slices carried forward) shows the gap is much smaller than
assumed:

- `ReviewService.build_section` (the write/propose decision logic) is
  **already fully ported** to `application/review.py:156-206`, complete and
  tested. It takes `body` plus 6 pre-computed hash strings.
- 4 of those 6 hashes are **already implemented** in `EvidenceService`
  (`rules_hash`, `contract_hash`, and the generic `manifest_hash` covers both
  `source_manifest_hash` and `code_evidence_manifest_hash`).
- `prompt_hash` is not an "AI prompt hashing concept" — legacy hashes every
  `.md` file under `prompts_dir` (`tesina_harness.py:433-439`). Plain file
  hashing, same shape as the already-ported `rules_hash`.
- `source_hash` similarly hashes every `.md` file under the doc's context
  directory plus `manual_dir`, combined with the config's section list
  (`tesina_harness.py:417-430`).
- `render_section_draft` (`tesina_harness.py:1311-1378`) is a **deterministic
  markdown scaffold generator** — a title, a fixed disclaimer, a bulleted
  summary of the context topics consumed by the section, a `PENDIENTE:` list
  derived from the section contract's `required_content`, and an optional
  APA-sources placeholder block. No LLM call. All fields it reads
  (`toc`, `required_content`, `apa_required`, `references_list`,
  `Topic.consumed_by`) already exist on the current `Template`/`SectionContract`
  Pydantic models — no domain modeling gap remains there either.

So the actual missing surface is: 2 small hash functions, 1 small pure
scaffold-rendering function (plus 3 small helpers it calls), and rewiring 2
call sites that already exist as clean, documented stubs
(`PipelineService.stage_build_sections`'s `NotImplementedError` and the CLI's
`build-section` command's `typer.Exit(1)`).

## 2. Goals & Non-Goals

### Goals

- Byte-for-byte behavioral parity with the legacy scaffold text, PENDIENTE
  markers, and hash payload shapes (confirmed with the user: this is a
  faithful port, not a redesign, matching the philosophy of all 15 prior
  slices).
- Zero new services, zero new ports, zero new constructor wiring — extend
  the two services (`EvidenceService`, and `PipelineService` via a new public
  method) and one domain module (`domain/sections.py`) that already own the
  adjacent concerns.
- Close both existing stub call sites (`stage_build_sections`, CLI
  `build-section`) so `docs pipeline prep`/`docs pipeline all` can finally
  complete successfully.

### Non-Goals

- No AI/LLM integration of any kind — `render_section_draft` is, and
  remains, a pure deterministic function.
- No change to `ReviewService.build_section`'s existing signature or write/
  propose logic — it is correct and tested as-is.
- No change to `PipelineService.__init__`'s constructor (out of scope,
  already accepted as a legitimate composition-root in Slice 16).

## 3. Key Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | `source_hash`/`prompt_hash` join `EvidenceService` as two new methods, backed by two new pure payload-builder functions in `domain/evidence.py` | Sibling to the already-ported `rules_hash`/`contract_hash`/`manifest_hash`, same application/domain split those already use |
| 2 | ~~`render_section_draft` + its 3 helpers land in `domain/sections.py`~~ **Correction (found during planning, see plan's Judgment call 1): they already exist, complete and unit-tested, in `domain/section_rendering.py`.** `domain/sections.py` only holds frontmatter/stamping concerns (`apply_stamp`, `with_frontmatter`, `infer_section_id_from_path`) — a different module. The plan imports the existing renderer; it recreates nothing. | Verified via direct `Read` of both files during plan-writing; avoids DRY violation / a second diverging implementation |
| 3 | Per-section context is read via `Template.context_schema.topics` filtered by `topic.consumed_by`, via **`ContextRepository.read_topic_raw`** (not `read_topic` as originally written here — corrected during planning, see plan's Judgment call 2), not by parsing the generated `context/index.json` | The index is a derived artifact for humans; the schema's `consumed_by` field is the source of truth already used elsewhere (`json_context_repository.py:65`). `read_topic_raw` is required because `_summarize_context` regexes raw markdown table syntax — `read_topic`'s already-parsed return value would raise `TypeError` or silently degrade output |
| 4 | Orchestration (render → gather 6 hashes → call `review_service.build_section`) becomes a new **public** method `PipelineService.build_section(doc_id, template, section_id, config) -> Path` | `PipelineService` already holds `review_service`, `evidence_service`, `context_repository`, `workspace` — zero new DI. Mirrors Slice 16 Tasks 3–4's established convention of public orchestration methods on `PipelineService` that both the CLI and pipeline-stage closures call through |
| 5 | `stage_build_sections` (private stage closure) loops sections and calls `self.build_section(...)`; the CLI `build-section <id>` command calls `deps.pipeline.build_section(...)` for one section | Matches the existing `build-ledger` CLI command's pattern (`deps.pipeline.context_confirmed_lines(...)` + `deps.evidence.render_fact_ledger(...)`) — no new CLI wiring pattern introduced |

## 4. Architecture

No new boxes. Two existing application services gain methods, one existing
domain module gains pure functions, two existing stub call sites get wired:

```
cli/main.py: build-section <id>          (Exit(1) stub -> real call)
        │
        ▼
application/pipeline.py: PipelineService.build_section(doc_id, template, section_id, config)   ◀── NEW public method
        │                                                                                          also called in a loop from stage_build_sections
        ├──▶ domain/sections.py: render_section_draft(...)                                      ◀── NEW pure function (+3 helpers)
        ├──▶ application/evidence.py: EvidenceService.source_hash(...)                          ◀── NEW method
        ├──▶ application/evidence.py: EvidenceService.prompt_hash(...)                          ◀── NEW method
        ├──▶ application/evidence.py: EvidenceService.rules_hash / contract_hash / manifest_hash    (existing, unchanged)
        └──▶ application/review.py: ReviewService.build_section(...)                                (existing, unchanged)
```

## 5. Data Flow

For a given `section_id`:

1. Resolve `Section` + `SectionContract` from `Template`.
2. Filter `Template.context_schema.topics` to those whose `consumed_by`
   contains `section_id`; read each via `context_repository.read_topic`.
3. `render_section_draft(section, contract, context, keyword_bold_terms)` →
   markdown `body` (pure).
4. Compute 6 hashes: `evidence_service.source_hash/prompt_hash/rules_hash/
   contract_hash` + `manifest_hash` (×2, for source and code-evidence
   manifests).
5. `review_service.build_section(doc_id, template, section_id, body,
   **hashes)` → writes the section, updates it in place, or writes a
   `_proposals/*.candidate.md`, exactly as it does today.

## 6. Error Handling

No new error paths. Inherits existing behavior: `ReviewService.build_section`
already raises on unknown `section_id` (via its `next(s for s in
template.sections ...)` lookup — unchanged); `EvidenceRepository`'s
`file_exists`/`hash_file` already handle absent files (return `""` via
`manifest_hash`, matching legacy's `manifest_hash(path_value: str | None)`).

## 7. Testing

Aggressive TDD, matching Slice 16's discipline: RED before every
implementation step, full suite green (`rtk proxy uv run pytest -q`) before
every commit, one task per reviewable unit. Unit tests for the new pure
functions (`render_section_draft` and its helpers, the 2 new hash-payload
builders) using real fixture data, not mocks. Integration tests for the 2 new
`EvidenceService` methods, the new `PipelineService.build_section` method,
and the CLI command, following the existing `tests/integration/test_*`
conventions in this codebase. A characterization test comparing the new
scaffold's output against a byte-for-byte transcription of the legacy
`render_contract_scaffold` output for a synthetic section is the parity
proof this design's Goal 1 requires.
