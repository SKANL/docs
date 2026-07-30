# Proposal: Universal Schema Harness

## Intent

The harness claims to be document-type-agnostic but is **estadía-TIC in practice**.
Its founding refactor made rendering/pipeline/asset-kinds format-agnostic yet left
**document-type policy hardcoded** in `rules.py`/`doctor.py`/`evidence.py`. First real
use of a second template (`documento-generico`) proved it: `review-rules` fails
because APA is disabled by design, `build-rules` raises `KeyError` on empty `paths`,
`doc new` never creates the ingest `inbox/`, and inbox subfolders are silently invisible.
The `Template` model already carries `extra="allow"` + `Document.overrides` deep-merge —
**the AI-generated schema the vision asks for is the Template itself**; the code just
refuses to read it. Fix: read policy from the resolved template, never hardcode it, and
generate every mechanical artifact (manifests, queues, figure catalog, gap report) so the
code agent only reasons and fills validated slots.

## Scope

### In Scope
- **Policy de-hardcoding**: convert 6 hardcoded `_check_*` (items #1-6) to template-declared
  conditional/consistency checks; evacuate `normative.py` defaults (#9) to template data.
- **First-use bugs**: `build-rules` KeyError guard (#8); `doc new` creates `inbox/` (#10);
  `evidence.py:41` literal `normative_source` (#7); orphan `_media/` cleanup (#13-media).
- **Recursive ingest** (#11): walk subfolders, relative-path provenance as a signal, loud
  reporting of everything ignored/unsupported; `_detection.json` converted-this-run vs
  already-present semantics (#12, per-directory JVM look-ahead).
- **Source roles**: classify each source (normative / example / evidence) by signals with a
  pending-classification queue the agent confirms; role recorded in the source manifest.
- **Duplicates**: near-duplicate detection (normalized similarity), highest-fidelity kept,
  decision recorded in the manifest — auditable, reversible, never silent.
- **Verbatim assets**: `inbox/assets/` convention + heuristic detection; pending-placement
  queue (cover/front/back); pre-ingest routing so declared assets never hit flatteners;
  placement recorded in a manifest.
- **Figure catalog**: deterministic (hash, dims, origin, source subfolder); captioned
  figures referenceable by sections; AI knows which figures exist.
- **Template lifecycle**: `template init` (documented skeleton), `template validate`
  (structure + completeness before use); **gap report** (context fields + section
  `required_content`) — draft proceeds with PENDIENTE markers, strict blocks.

### Out of Scope
- The 5 fixed context-curation topics stay fixed (keywords/tone/structure/writing-style/formatting-rules).
- No new output formats; no renderer changes beyond asset placement needs.
- No new rule DSL / rule-engine (Approaches 2 & 3 rejected — new trust surface).

## Capabilities

### New Capabilities
- `document-template`: template lifecycle (`init`/`validate`) and the universal-schema
  contract — all document-type policy is template-declared data; the harness enforces
  structural consistency and completeness, never hardcoded values or literals; normative
  defaults live in the template, not in domain code.

### Modified Capabilities
- `document-pipeline`: template-driven (not hardcoded) `review-rules` checks; `build-rules`
  guards absent paths instead of raising; machine-readable gap report drives draft/strict split.
- `document-ingest`: recursive scan with relative-path provenance and loud reporting; source-role
  classification with pending-classification queue + manifest; near-duplicate detection with
  fidelity preference recorded; `_detection.json` run-vs-prior semantics; orphan `_media/` cleanup.
- `asset-management`: verbatim-asset pre-ingest routing (folder + heuristic); pending-placement
  queue; placement manifest; deterministic captioned figure catalog as referenceable assets.
- `context-curation`: **None** (explicit non-goal). `document-render`: **None**.

## Approach

**Approach 1 from exploration** — extend the existing `Template` as the single universal
schema. The `extra="allow"` model + `Document.overrides` deep-merge already implement
"schema over template"; only `rules.py`/`doctor.py`/`evidence.py` bypass it. Every hardcoded
check becomes conditional and internally-consistent: `_check_apa7_enabled` deleted (the
`Apa7Config.enabled` gate `review_apa7_text` already respects suffices); preliminaries/margins/
extracted-dir checks fire only when their block is declared, comparing against the template's
own values rather than literals. Two working fixtures become the acceptance tests. Mechanical
artifacts (manifests, queues, figure catalog, gap report) are new deterministic writers that
follow the no-timestamps/atomic-write discipline; the AI fills validated slots only — output
is always validated, never trusted blindly. This honors the vision **without** a second
schema artifact (Approach 2) or an AI-authored rule DSL (Approach 3), both of which add
unvalidated trust surface the model already avoids.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `domain/rules.py` | Modified | `_check_*` become template-declared conditional/consistency checks |
| `domain/normative.py` | Modified | Spanish-thesis defaults evacuated to template data |
| `domain/evidence.py` | Modified | Remove hardcoded `normative_source` literal (#7) |
| `application/evidence.py` | Modified | Guard absent `paths` (#8 KeyError) |
| `application/documents.py` | Modified | `doc new` creates `inbox/` (#10) |
| `application/ingest.py` | Modified | Recursive scan, provenance, loud reporting, roles, duplicates |
| `infrastructure/ingest/opendataloader_pdf_adapter.py` | Modified | Per-directory look-ahead; run-vs-prior status |
| `application/context.py` (`ContextService`) | Modified | Gap report + section `required_content` gaps |
| `cli/` (template, asset) | New/Modified | `template init`/`validate`; asset placement queue |
| New writers | New | source manifest, placement manifest, classification/placement queues, figure catalog |
| `tests/unit/domain/test_rules.py` + suite | Modified | `_valid_extra()` baseline (~15 tests) rewritten |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Regression on `reporte-estadia-tic` (only real user) | High | Byte-behavior-identical proof; structural "no estadía-literal" guard test |
| Test-suite blast radius (~923 tests, strict TDD) | Medium | Rewrite `_valid_extra()` baseline first; front-by-front slices |
| JVM look-ahead redefines "sibling" under recursion | Medium | Decide per-directory batching explicitly in design |
| Determinism regression from new writers | Medium | Reuse `deterministic_zip`/atomic-write; `is_context_content_filename` for `context/` |
| AI-authored template/queue/classification trusted blindly | Medium | `template validate` before use; every queue confirmed by agent+user |
| Multi-front scope creep | Medium | Chained PR slices (design/tasks decide boundaries); ask-on-risk |

## Rollback Plan

Fronts are independent and largely additive. Policy de-hardcoding reverts by restoring
`rules.py`/`evidence.py` (templates are data — no data migration). New commands/writers
(`template init/validate`, manifests, queues, figure catalog, gap report) sit behind new
CLI entry points and flags, so removing them leaves existing pipelines unchanged. Revert
per-slice PR; no persisted-state migration to unwind.

## Dependencies

- No new runtime dependencies. Builds on existing `Template`/`Document.overrides`,
  `AssetService`, `ContextService`, `ingest_naming`, and determinism utilities.
- Frozen `openspec/specs/*` are the delta baseline; policy hardcoding is implementation
  drift and deltas cleanly.

## Success Criteria

- [ ] `documento-generico` passes `doctor`, `review-rules`, `build-rules`, and `prep` with zero errors.
- [ ] `reporte-estadia-tic` stays byte-behavior-identical (regression + no-hardcoded-literal guard).
- [ ] Recursive drop of the real folder tree produces source manifest, role/placement/classification
      queues, figure catalog, and machine-readable gap report — nothing silent.
- [ ] `template init` emits a valid documented skeleton; `template validate` rejects an incomplete
      template before use.
- [ ] Determinism suite stays green across two independent runs (byte-identical outputs).
- [ ] No hardcoded document-type policy or `normative_source` literal remains in domain code.
