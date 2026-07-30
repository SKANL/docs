# Design: Harness Generality & Revision

## Technical Approach

Close three generality gaps within the existing hexagonal seams — almost every
seam already exists, so most items are wiring, not new architecture. Prior
changes already evacuated most rule lexicons to config (`domain/normative.py`,
`resolve_normative_settings` at `pipeline.py:229`), added `DocumentRendererPort`
+ a format-keyed registry (`Deps.resolve_renderer`, `core_app.py:67`), and a
LibreOffice PDF subprocess (`libreoffice_qa_adapter.py:27`). We reuse all of it.
Each item is one thin, independently-revertable PR.

## Architecture Decisions

### A. Template-driven review rules

**Choice**: Thread the *one* remaining hardcoded lexicon —
`DEFAULT_CONTESTED_STACK_TERMS` (`rules.py:571`) — through config, reusing the
existing `NormativeSettings` seam. Estadia's `cross_consistency.contested_stack_terms`
block already exists but is empty (`reporte-estadia-tic.json:185`) and unused;
populate it with today's 6 terms and pass it into `review_cross_consistency`
(the call at `review.py:103` currently passes nothing → falls back to the
constant). Add `citation_style` (`apa7|none`) as the canonical selector in the
`apa7` block; `none` sets `apa7.enabled=false`. Keep the apa7 implementation
untouched (the future-style seam is `citation_style`, not new code).
**Alternatives**: new typed pydantic `ReviewRules` model on `Template` —
rejected: `normative`/`apa7`/`cross_consistency` already live in config +
`model_extra`; a parallel typed block duplicates the seam. **Rationale**:
absent-config == today's behavior is already true for every lexicon *except*
contested-stack; this closes the last one with a 3-line thread + a data edit,
gated by the estadia characterization test.

### B. `doc revise` loop → new `document-revise` capability

**Choice**: `RevisionService` (application) reusing `SectionRepository`,
`ReviewService.review_section`/`review_document`, `stamp_section`, and
`ContextService.build_gap_report`. Flow: `doc revise <section> "<request>"`
snapshots the pre-edit body to `sections/_revisions/NNN-<id>.<n>.md`, lets the
agent edit, then computes `difflib.unified_diff(before, after)`, re-runs review
on the changed section + `review-document`, restamps provenance, and appends one
entry (`request`, `section_id`, `diff_path`, `body_hash` before/after, `now`) to
`sections/_revisions/revision-log.json`. Context-topic ripple: when a `context`
topic changes, map `Topic.consumed_by` (`template.py:20`) → dependent sections
and FLAG them in the log for re-review (v1 flags; no auto re-scaffold).
**Alternatives**: git-backed diff — rejected (proposal: `.md` + no VCS); store
snapshot in frontmatter — rejected (body_hash already detects change; a real
before-file gives a readable diff). **Rationale**: diff is stdlib, snapshot dir
mirrors existing `_proposals`/`_context` convention, provenance reuses
`apply_stamp`.

### C. HTML + PDF renderers → `DocumentRendererPort`

**Choice**: `HtmlRendererAdapter` (`output_format="html"`, pandoc md→HTML,
deterministic — no timestamps in HTML) and `PdfRendererAdapter`
(`output_format="pdf"`, converts the DOCX draft via the existing
`LibreOfficeQaAdapter.render_docx_to_pdf`; WARN+skip if soffice absent). Both
register in the composition-root registry; `pipeline`/`build` select via the
existing `resolve_renderer`. Add `--format` to the assemble CLI (repeatable);
default stays `docx` so current behavior is unchanged. **Alternatives**: PDF via
pandoc/LaTeX — rejected (heavy toolchain; DOCX→PDF reuses the wired soffice path
and inherits docx fidelity). **Rationale**: PDF-from-docx reuses a tested
subprocess; HTML is a one-call pandoc format switch.

### D. 2nd built-in template

**Choice**: `technical-report-srs.json` (English, `citation_style=none`,
different `subjective_terms`/`contested_stack_terms`, structurally different
sections) as package data beside estadia/generico, plus an e2e acceptance test
that builds it green — proving A's config-drive. **Rationale**: a non-APA
template is the only real proof that no Spanish-APA literal remains in domain.

### E. Clean-room AGENTS.md (verify-phase activity, not code)

**Choice**: verify-phase runs the full workflow using ONLY `AGENTS.md` §1 + raw
files; every step that needs source/tests to succeed is a gap fed back as an
additive `AGENTS.md` edit. Amend §5 for PDF (see C/rollout).

### F. Lifecycle-lite

**Choice**: `lifecycle` (`draft|final`, user-set) on `document.json`; build
version+timestamp appended to `runs/` on assemble (already the non-deterministic
command log). `doc status` (`StatusService`, `status.py:20`) surfaces both.
**Rationale**: timestamps MUST stay out of the byte-deterministic artifact;
`runs/` is already wall-clock, `document.json` is state not a rendered output.

## Data Flow

    doc revise ──► snapshot before ──► agent edits ──► unified_diff
        │                                                  │
        └─► review-section + review-document ◄─────────────┘
                          │
                          ▼
            restamp + revision-log.json (+ ripple flags from consumed_by)

    pipeline assemble --format {docx,html,pdf}
        └─► resolve_renderer(fmt) ──► RendererPort.build()  (pdf: docx ─soffice─► pdf)

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `domain/rules.py` | Modify | Delete `DEFAULT_CONTESTED_STACK_TERMS`; take terms from caller |
| `domain/normative.py` | Modify | Carry `contested_stack_terms`, `citation_style` in `NormativeSettings` |
| `application/review.py` | Modify | Pass `normative.contested_stack_terms` into `review_cross_consistency` |
| `templates/builtin/reporte-estadia-tic.json` | Modify | Populate the 6 current contested terms (compat) |
| `application/revision.py` | Create | `RevisionService` (diff, re-review, provenance, ripple) |
| `cli/commands/*` | Modify | `doc revise`; assemble `--format` |
| `application/html_render.py` | Create | `HtmlRendererAdapter` |
| `application/pdf_render.py` | Create | `PdfRendererAdapter` (reuses `render_docx_to_pdf`) |
| `cli/_shared.py` | Modify | Register html/pdf renderers; wire `RevisionService`; lifecycle |
| `templates/builtin/technical-report-srs.json` | Create | 2nd template (non-APA) |
| `application/status.py`, `domain/document_status.py` | Modify | Lifecycle + build version |
| `AGENTS.md` | Modify | §5 PDF non-determinism; §1 clean-room gaps |

## Interfaces / Contracts

- `NormativeSettings` gains `contested_stack_terms: list[str]`, `citation_style: str="apa7"`.
- `RendererPort` unchanged — html/pdf are new `output_format` implementations.
- `RevisionService.revise(doc_id, template, config, section_id, request) -> RevisionResult`.
- `revision-log.json`: `{schema:1, entries:[{request, section_id, diff_path, before_hash, after_hash, ripple:[...], ts}]}`.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | contested-terms from config; citation_style=none disables apa7; diff/ripple | RED-first; empty config == today |
| Integration | estadia byte-identical after A; HTML deterministic (double-build); PDF WARN+skip when soffice absent | characterization + determinism harness |
| E2E | 2nd template builds+reviews green (D); `doc revise` produces diff+provenance; `doc status` shows lifecycle | acceptance tests |

## Threat Matrix

Git/PR/routing/executable-classification rows: **N/A** — no VCS, PR, routing, or
file-classification surface added. Process-integration note (applicable): HTML
(pandoc) and PDF (soffice) run as fixed-argv subprocesses, no shell string, no
user-interpolated args — identical to existing `render_pandoc`/
`render_docx_to_pdf`. Missing toolchain → WARN+skip, never crash (RED test:
absent-soffice path).

## Migration / Rollout

No data migration. `--format` defaults to `docx` (no behavior change). AGENTS.md
§5 amended: PDF is a *derived, non-byte-deterministic* artifact (soffice output
varies by version); the reproducibility guarantee binds `.md`→`.docx`/HTML only.

## PR Slicing (chained, ≤400 lines, stacked-to-main)

1. **Template-driven-rules refactor** (A) — mechanical, backward-compat gated by estadia characterization test. FIRST.
2. **HTML renderer** (C-html) — deterministic, low risk.
3. **PDF renderer** (C-pdf) — reuses soffice; WARN+skip.
4. **`revise` loop** (B) — new capability, highest logic.
5. **2nd template + acceptance** (D) — proves A end-to-end.
6. **Lifecycle + `doc status`** (F).
7. **AGENTS.md clean-room refinement** (E) — verify-phase output.

## Open Questions

- [ ] Snapshot retention: keep every `_revisions/NNN-<id>.<n>.md` or last-N? (default: keep all; prune deferred)
- [ ] HTML: single-file (`--self-contained`) vs. sidecar assets? (default: single-file, deterministic)
