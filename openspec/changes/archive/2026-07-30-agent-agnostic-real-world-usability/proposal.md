# Proposal: Agent-Agnostic Real-World Usability

## Intent

This session the harness produced a real document end-to-end only because a human-driven Claude Code agent supplied heavy manual glue: setting env vars every call, placing the manual at an exact hardcoded path, hand-assigning `Figura N`/`Tabla N`, hand-classifying an arbitrary file dump, wiring a PDF renderer by hand, and rewording prose to satisfy over-eager review rules. None of that glue ships with the harness. Goal: make `docs` usable end-to-end by ANY code agent (Claude Code, Codex, OpenCode) over plain CLI + files — bring-your-own-agent — and robust to messy real-world input, without that glue. Layered: an agent-native mechanical core plus a guided layer on top. Target user: a developer driving the harness through a code agent.

## Bound Decisions (non-negotiable)

1. **Bring-your-own-agent.** Harness stays MECHANICAL and ships a documented agent contract. NO embedded LLM, NO API keys inside the harness. Any agent drives it via CLI + files; the model only fills cognitive slots.
2. **Messy input → auto-classify by CONTENT + graceful DEGRADATION, fail-OPEN.** `doctor` WARNs with actionable next-steps instead of hard-failing on optional inputs; the document still generates with clearly-marked gaps plus a human/agent-readable intake & gap report.
3. **Reproducibility boundary.** The section `.md` files (agent-authored prose) are the durable source of truth; the `.docx` is a deterministic function of them. Byte-determinism applies to the BUILD, not the prose. State explicitly (item M).

## Scope

### Resolved (A–M)

| # | Gap (evidence) | Decision / approach |
|---|---|---|
| A | Workspace roots read ONLY from env vars, cwd-relative defaults, no config/init (`cli/_shared.py:64 build_workspace`) | Persisted workspace config with precedence **config file → env → default**; add `doc init` bootstrap. Reuse `Workspace`; no new abstraction. |
| B | No shipped agent guide (no `AGENTS.md`; `RESUME.md` is SDD-dev-only) | Ship canonical agent-agnostic contract: `AGENTS.md` and/or `docs guide` covering full workflow (ingest→context→prep→author→review→assemble→verify), config, figure/table conventions, `review-section --json` iterate-to-green loop, cognitive-slot boundary. |
| C | `reporte-estadia-tic` template lived ONLY under `tests/fixtures/templates/` | Ship built-in templates as package data + `template list --available` and `template use <builtin>` (copy into workspace). Consider `template init` from a dropped writing-guide. |
| D | `classify()` keys off folder-name lexicon; flat arbitrary dump → all `unknown`/`low` (`domain/source_role.py:51`) | Add deterministic content heuristics (type/extension, PDF title/headings, keyword signals in first N bytes) with confidence threshold: high → act, low → queue for confirmation. No LLM. Modifies `document-ingest`. |
| E | `manual_dir` hardcoded under `{inbox}/guides/manual-estadia-tic`; doctor HARD-FAILS when absent (`application/doctor.py:32`, `domain/doctor.py:22 passed`) | Auto-detect manual anywhere under inbox by content; make optional-input checks WARN not FAIL (`required=False`); `passed` must not fail on optional inputs; emit actionable next-steps. |
| F | `Pdfium2PdfRenderAdapter` (`infrastructure/pdf/pdfium2_pdf_render_adapter.py`, PR #19) is UNWIRED | Wire into ingest so vector-only PDFs (zero raster from opendataloader) get pages/figures into `sections/figure-catalog.json`. Degrade cleanly if render toolchain absent. |
| G | Raw `gap-report.json` + `00-fact-ledger.md` PENDIENTE not human/agent-readable | Single "what I found / what's missing / how to finish" report: intake report at ingest + finish-checklist. |
| H | Orchestrator hand-assigned `Figura N`/`Tabla N` and renumbered on edits | Number figures/tables in document order and resolve `Ver Figura N` cross-refs at build/assemble; authors use stable labels/anchors, not hard numbers. Modifies `document-render`. |
| I | No `doc status` (doc_app has new/list/current/show/use/rename/delete) | Add resumable status: context filled?, N/M sections authored vs scaffold, which need review, ingested?, assembled? |
| J | Review false positives cost wasted turns (`domain/rules.py`: subjective-word, literal required-content keywords, `DEFAULT_CONTESTED_STACK_TERMS:511` flags legit `Firebase`) | Make heuristics precise/evidence-aware. (Pending-substring FP already fixed PR #19 via `\bpendientes?\b`.) |
| K | Cross-source conflicts (e.g. bun.js/TS vs PHP/Laravel) caught only by agent luck | Detect conflicting facts across ingested sources; surface as WARNING in intake/ledger. Modifies `document-ingest`. |
| L | Minimal toolchain undocumented / unvalidated | `doctor` validates required toolchain (uv, pandoc); declares figure-rendering (opendataloader/java; optional mermaid/Chrome/node, pypdfium2/pillow) as OPTIONAL degradable capabilities with WARN guidance. |
| M | Reproducibility boundary implicit | Capture bound decision 3 as an explicit design principle / spec statement. |

### Out of Scope (non-goals)

- NO embedded LLM, NO API keys, NO network calls inside the harness.
- NO GUI, NO web UI, NO daemon/server.
- NOT touching the active `universal-schema-harness` change.
- No new heavy dependencies for what a few deterministic lines cover (ponytail).
- No speculative multi-template abstractions beyond built-in provisioning (C).

## Capabilities

### New Capabilities
- `workspace-config`: persisted workspace config (config → env → default) + `doc init` bootstrap (A).
- `agent-contract`: shipped agent-agnostic guide — `AGENTS.md` and/or `docs guide` (B).
- `template-provisioning`: built-in templates as package data + `template list --available`/`template use` (C).

### Modified Capabilities
- `document-ingest`: content-based classification (D), PDF render wired into ingest (F), intake/gap report (G), cross-source conflict detection (K).
- `document-pipeline`: doctor fail-open + manual auto-detect (E), `doc status` (I), toolchain/optional-capability validation (L), reproducibility-boundary principle (M).
- `document-render`: automatic figure/table numbering + cross-ref resolution at build (H), precise/evidence-aware review rules (J).

## Approach

Layered. Mechanical core first: fail-open doctor + config/init + content classification + PDF wiring + numbering/cross-ref + precise review rules — each reusing existing ports/helpers (`Workspace`, `classify`, `DoctorResult`, figure-catalog, `review_rules`), no new abstractions. Guided layer on top: shipped `AGENTS.md`/`docs guide`, `doc status`, intake/gap report, built-in template provisioning. Strict TDD (RED first); determinism of the build preserved; CLI strings Spanish, code/docs English. Builds on PR #19 (branch `fix/docx-figures-and-apa-review`): APA consolidated-bib awareness, inline-image preservation, in-place tables, `Pdfium2PdfRenderAdapter`, word-boundary pending check.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `cli/_shared.py`, new config loader, `doc init` | Modified/New | Workspace config + bootstrap (A) |
| `AGENTS.md`, `docs guide` command | New | Agent contract (B) |
| package template data, `template` CLI | New | Built-in template provisioning (C) |
| `domain/source_role.py` + content probes | Modified | Content classification (D) |
| `application/doctor.py`, `domain/doctor.py` | Modified | Fail-open + manual auto-detect + toolchain (E, L) |
| ingest pipeline + `infrastructure/pdf/` | Modified | Wire PDF render adapter (F) |
| ingest reporting, fact-ledger | Modified | Intake/gap report + conflict WARN (G, K) |
| assemble/render + figure catalog | Modified | Figure/table numbering + cross-ref (H) |
| `cli/commands/doc_app.py` | New | `doc status` (I) |
| `domain/rules.py` | Modified | Precise review rules (J) |
| `openspec/specs/*` | Modified | Reproducibility principle (M) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Content classification misroutes arbitrary files | Med | Confidence threshold; low → queue for confirmation, never silent default |
| Fail-open hides a genuinely broken run | Med | Clearly-marked gaps + intake report + finish-checklist; strict mode still available |
| Precise review rules regress genuine catches | Med | Evidence-aware, TDD with both positive/negative fixtures |
| Figure/table renumbering breaks existing docs | Low | Deterministic order; anchors resolved at build; golden byte tests |
| Scope (A–M) exceeds 400-line PR budget | High | Slice into chained/stacked PRs (see below); sdd-tasks forecasts |
| Optional render toolchain absent on agent machine | High | Declared OPTIONAL; degrade with WARN + next-steps |

## Suggested Slice / PR Breakdown (chained, ≤400 lines each)

1. **Fail-open doctor + manual auto-detect + toolchain validation** (E, L) — unblocks real drops first.
2. **Workspace config + `doc init`** (A).
3. **Content-based classification + cross-source conflict WARN** (D, K).
4. **Wire PDF render adapter into ingest** (F).
5. **Figure/table numbering + cross-ref resolution at build** (H).
6. **Precise/evidence-aware review rules** (J).
7. **Intake/gap report + `doc status`** (G, I).
8. **Built-in template provisioning** (C).
9. **Shipped agent contract (`AGENTS.md`/`docs guide`) + reproducibility-boundary principle** (B, M).

Ordering: mechanical core (1–6) before guided layer (7–9). sdd-tasks owns final PR boundaries.

## Rollback Plan

Each item is additive and independently revertable per PR. Config precedence falls back to existing env-var behavior if no config file present (A). Doctor fail-open is gated so `--strict` restores hard-fail. PDF wiring degrades to current behavior when the toolchain is absent. Revert any single PR without affecting shipped PR #19 fixes.

## Dependencies

- Builds on PR #19 (`fix/docx-figures-and-apa-review`), already merged/in-branch.
- Optional runtime: opendataloader/java, pypdfium2/pillow, mermaid/Chrome/node — all degradable, none required.

## Success Criteria

- [ ] A fresh agent generates a document from a flat, arbitrarily-named drop with NO manual glue and NO env-var setup.
- [ ] `doctor` WARNs (not FAILs) on missing optional inputs; document still generates with marked gaps + readable intake/gap report.
- [ ] Content classification routes a mixed dump correctly or queues low-confidence items; no silent misroute.
- [ ] Vector-only PDFs land figures in the catalog automatically when the render toolchain is present.
- [ ] Figures/tables auto-numbered in document order; `Ver Figura N` resolves at build.
- [ ] Review rules stop flagging legitimate `Firebase`/subjective/plural-token usage while still catching real issues.
- [ ] `AGENTS.md`/`docs guide` lets an agent drive the full workflow without reading source/tests.
- [ ] `doc status` reports a resumable summary; build byte-determinism preserved.

## Proposal question round

Bound decisions and A–M are pre-agreed; these product questions would only refine, not block:

1. Low-confidence classification (D) — proceed with a WARN-marked best guess, or hold the file out of the document until the agent confirms? (Assumed: queue/hold, never silent default.)
2. Agent contract (B) surface — is a shipped `AGENTS.md` sufficient, or is a `docs guide` command required so the contract is queryable from the CLI? (Assumed: both, `AGENTS.md` authoritative.)
3. Figure numbering (H) — number strictly in section/document order, or honor any explicit author-declared order when present? (Assumed: document order, anchors stable.)
