# Proposal: Harness Generality & Revision

## Intent

Post `agent-agnostic-real-world-usability`, any agent can drive the harness, but three gaps block it from being a general document harness: (1) the review/rules layer is hardcoded to Spanish-APA-estadia, so it cannot serve a different document TYPE; (2) there is no post-completion semantic revision flow (only mechanical find/replace); (3) only DOCX is wired despite a clean renderer seam. Close all three, and prove generality with a second, structurally-different template.

## Scope

### In Scope (bound decisions)
- **A. Template-driven review rules** — move rule DATA (citation style, contested-stack/subjective/forbidden terms, format params) out of `rules.py`/`source_role.py` into template config. Estadia declares CURRENT values → byte-identical. Pure refactor of WHERE data lives.
- **B. `doc revise` loop** — agent edits section `.md`; harness provides diff (section before/after + summary), scoped re-validation of affected sections + `review-document`, and change provenance (request text + sections + timestamp). Covers prose edits AND rippling context-topic edits.
- **C. HTML + PDF renderers** — HTML deterministic (pandoc md→html); PDF best-effort (soffice/pandoc, WARN+skip if absent). Both implement `DocumentRendererPort`. CLI selects format(s).
- **D. Second built-in template** — English non-APA technical-report/SRS as package data + e2e acceptance test using DIFFERENT rule config; validates A.
- **E. Agent-contract clean-room** — verify-phase clean-room run (AGENTS.md + arbitrary raw files only) → refine `AGENTS.md`.
- **F. Lifecycle/version** — record draft/final + build version on assemble; surface via `doc status`.

### Out of Scope
- GUI/wizard; citation styles beyond apa7 (seam only); embedded LLM/API keys; full VCS (git + `.md` is the store); structural/template changes and source re-ingest in `revise` (existing flows); the active `universal-schema-harness` change.

## Capabilities

### New
- `document-revise`: revise loop — diff, scoped re-validation, provenance (B).
- `document-lifecycle`: lifecycle state + build version, `doc status` (F).

### Modified
- `template-provisioning`: templates carry review-rule data + ship 2nd non-APA template (A, D).
- `document-pipeline`: review/rules read from template config; PDF reproducibility-boundary amendment (A, C).
- `document-render`: HTML + PDF renderers, format selection (C).
- `agent-contract`: clean-room-refined `AGENTS.md` (E).

## Approach (anchors)

| Item | Reuse / touch |
|---|---|
| A | `domain/rules.py:1-30,511`, `domain/source_role.py`, `domain/models/template.py` |
| B | reuse `application/corrections.py` provenance surface, `build_gap_report`, `stamp-section` |
| C | `domain/ports/document_renderer_port.py`, `application/docx_assembly.py:18-35`, `domain/pipeline.py` |
| D | template package-data + acceptance test |
| E | `AGENTS.md` §5 |
| F | `document.json`/`runs/` + `doc status` |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Rules refactor breaks estadia | High | Estadia config = current values; characterization/acceptance tests stay green; RED-first |
| PDF non-deterministic | High | Declare PDF derived/non-byte-deterministic; amend reproducibility boundary; WARN+skip on missing toolchain |
| Revise scope creep | Med | v1 = prose + rippling context only; defer structural/re-ingest |

## Rollback

Per-slice revert; each PR is autonomous. A is a pure refactor — revert restores hardcoded rules with no data change.

## Dependencies

pandoc (HTML); soffice/pandoc optional (PDF, degrades if absent).

## Success Criteria

- [ ] Estadia output byte-identical; all existing tests green after A.
- [ ] 2nd template builds + passes review with non-APA config (D).
- [ ] HTML byte-deterministic; PDF degrades gracefully.
- [ ] `doc revise` produces diff + scoped re-validation + provenance.
- [ ] `doc status` shows lifecycle + version.

## Suggested slices (≤400 lines, chained)

1. Template-driven rules refactor (estadia defaults) → 2. HTML renderer → 3. PDF renderer → 4. `revise` loop → 5. 2nd template + acceptance → 6. lifecycle/`doc status` → 7. AGENTS.md clean-room refinement.
