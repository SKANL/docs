# UX modes and hardening

## Objective
Make the harness safe to rely on and understandable to use: fix the data-loss
and authorization risks found in the 2026-10-14 full-repo analysis, remove dead
code and stale documentation, and redesign Review Studio (web and desktop) around
two user-chosen working modes plus an Advanced switch that hides technical
surface.

## Problem (evidence: analysis 2026-10-14)
- Data at risk: JSON repositories write non-atomically and `load_registry`
  swallows a corrupt file and returns an empty registry (json_repository.py:28-40).
- Authorization gap: route knowledge lives in three tables (application.py,
  route_policy.py, operations.py); a route missing from one is unscoped.
- Two lock implementations; the ledger one has no owner token and rmtree's blindly.
- Dead / unwired code: domain/models/result.py, Run{Recorder,History,Reporter},
  domain/pipeline.py stage sets (no CLI `pipeline` command exists), PluginRunner.
- Docs drift: AGENTS.md lists a non-existent `docx` group and omits real groups;
  dangling sentence; ci.md cites missing tests; CLAUDE.md contradicts the code.
- UX: Home never says what the product is; workspace/document only switchable
  inside Configure; 7 flat nav items; Review exposes passport/attestation/digest;
  Sections packs 6 actions; run/build/release named three ways; English-only UI
  for a Spanish-first harness; desktop has no startup or failure screen.

## Product decision (user, 2026-10-14)
The user chooses how to work. Two modes, switchable at any time:
- **Supervisar**: the agent writes sections via CLI; the person uploads sources,
  reviews findings, checks the document and delivers.
- **Redactar**: the person writes and edits sections in the UI end to end.
Plus an **Avanzado** switch that reveals technical areas (tools, evidence,
baselines, graph, templates, diagnostics, plugins). Nothing is deleted from the
UI, only moved; CLI/API/UI parity tests must stay green.

## Scope
In: tasks below. Out: new backend capabilities, changing the pipeline stage
list, new export formats, auth model redesign.

## Constraints
- Strict TDD: failing test first (backend `uv run pytest`; frontend runner to be
  confirmed in review-studio/package.json before U1).
- Determinism rules in docs/CLAUDE.md (atomic_write, canonical_json, paths).
- Architecture tests must stay green (layering, ports, parity matrix).
- Generated artifacts and code in English; UI copy ships Spanish + English (U10).
- ~400 authored changed lines per task is a planning heuristic only.
- Conventional Commits, no AI attribution. Push/PR/merge remain the user's call.

## Tasks
Route: D = delegated writer, I = inline. Mark [x] only after observed outcome + checks.

### A. Data and security hardening
- [x] H1 (D) [bf0a2d18] Atomic writes in Json{Document,Section,Context,Evidence}Repository
      via infrastructure/atomic_write; `load_registry` raises a clear error on a
      corrupt file instead of resetting (keep the corrupt file untouched).
- [x] H2 (D) [98060771] ProvenanceLedger lock uses locking.owned_directory_lock (token
      ownership); corrupt ledger raises a clear error.
- [ ] H3 (D) API fails closed: a registered route with no scope entry is denied;
      add a test that introspects every registered route and asserts a scope.
- [x] H4 (D) [b86c7272] corrections: persist each applied id as it is applied, atomically.
- [ ] H5 (D) Sidecar: validate Host header (loopback names only); align body
      limits (128 MB vs 120 MB); replace hardcoded cursor HMAC secret with a
      per-install secret.
- [ ] H6 (D) java_on_path stops mutating os.environ (pass env to the subprocess).
- [ ] H8 (D) application/revision.py (~L179) has the same read-modify-write
      ordering as corrections (revision-log.json append + .diff numbering by
      glob count, unlocked, non-atomic): make it atomic and collision-safe.
- [ ] H9 (D) From review R3-corrections-no-dir-create: prove that
      atomic_write_text creates missing parent directories (the explicit mkdir
      was removed from corrections.py and the repositories); add a test writing
      into a missing parent for corrections and each repository.
- [ ] H10 (D) From review R3-ledger-stale-lock-test-weak: replace the removed
      competing-recoverer test with one covering a live-owner lock timing out,
      and pin the stale-lock test to explicit owner data instead of relying on
      owned_directory_lock internals.
- [ ] H7 (D) composition: hard imports (opendataloader_pdf, filetype, pypdfium2)
      become lazy with an actionable `doctor` message instead of killing the CLI.

### B. Cleanup and documentation truth
- [ ] C1 (D) Remove dead code with its tests: domain/models/result.py,
      RunRecorderService/RunHistoryService/RunReporter (+composition wiring),
      domain/pipeline.py legacy stage sets. Confirm no callers first.
- [ ] C2 (I) PluginRunner stays (tested sandbox) but docs state it is not wired
      into execution; no silent claim of plugin support.
- [ ] C3 (D) Fix documented drift: AGENTS.md command-group table (no `docx`
      group; add source/document/workspace/run; `publish` under `document`),
      dangling sentence, ci.md missing test names and job count, CLAUDE.md
      (`pipeline <set>` commands, ARCHITECTURE_REQUIRE_GRAPH, toolchains skip
      gate claim, ruff scope, layout list). Keep test_agents_md_content green.
- [ ] C4 (I) Lint `tools/` in CI (ruff scope) or document why not.

### C. UX: modes and information architecture
- [ ] U1 (D) Mode state: `mode` (supervise|write) and `advanced` persisted per
      browser (try/catch localStorage), React context + tests.
- [ ] U2 (D) Shell: topbar with workspace + document switcher, mode switch,
      Advanced toggle, theme toggle; remove "Review Studio foundation" footer.
- [ ] U3 (D) Navigation by mode/advanced (Supervisar: Inicio, Revisar, Entregar,
      Ejecuciones; Redactar adds Redactar; Avanzado adds Herramientas and
      Configuración técnica). Route map and palette follow the same rule.
- [ ] U4 (D) Home rewrite: what the product is, the 4-step flow, first-run mode
      chooser, one next action; distinguish "no workspace" from "no document";
      per-document (not workspace-wide) finding count.
- [ ] U5 (D) One vocabulary + in-context glossary; jargon (passport,
      attestation, digest, node ids) only under Avanzado.
- [ ] U6 (D) Empty states always carry a next-step button.
- [ ] U7 (D) Sections: primary actions (edit, save, review) vs advanced (stamp,
      pack context, build section); merge duplicate upload forms in Sources;
      single release entry point.
- [ ] U8 (D) Review: basic tabs (Findings, Artifacts, Compare) vs advanced
      (Evidence, Baselines, Quality, Graph).
- [ ] U9 (D) Friendly error mapping with collapsible technical details.
- [ ] U10 (D) i18n: dictionary layer, Spanish default + English, palette shows
      labels not raw CLI strings.
- [ ] U11 (D) Desktop: startup screen, sidecar failure screen with Retry and
      View log via existing Tauri commands.
- [ ] U12 (I) Verify in a running app: screenshots, a11y pass, parity matrix
      regenerated, specs updated.

## Acceptance criteria
- A corrupt registry.json is never silently reset; interrupted writes cannot
  truncate state files (tests simulate the interruption).
- Every registered API route has an enforced scope (test).
- A newcomer sees what the product does on first load and has one obvious next
  action; switching mode or workspace is possible from any screen.
- Default (non-Advanced) navigation shows at most 4 areas.
- No dead code listed in C1 remains; docs claims match the CLI (test-guarded).
- uv run pytest, ruff, mypy, frontend tests, architecture tests green.

## Checks
Backend: `uv run pytest` (full suite ~20-50 min; use focused runs while
iterating, full suite at task closure of each section), `uv run ruff check src tests`,
`uv run mypy src tools`. Frontend: runner TBD (review-studio).

## TDD
Strict, source: project CLAUDE.md. Runner: `uv run pytest`.

## Delivery
Strategy: ask-on-risk (default). Forecast: well over 400 authored lines, so a
chained-PR strategy (stacked-to-main or feature-branch-chain) must be chosen by
the user before the first push. Branch: feat/ux-modes-and-hardening.
Native review (RDD): assess per work-unit commit; record tier/outcome per task.

## Progress
Created 2026-10-14. H1, H2, H4 done (RED/GREEN observed by the writer).

Verification evidence (observed):
- Writer: tests/architecture 131 passed; ruff clean; mypy clean (335 files);
  focused run 198 passed on rerun. Full suite NOT run.
- Parent spot check: same focused command, 198 passed (46m36s, abnormally slow:
  machine under memory pressure). A second run was killed by the host for low
  memory and was not repeated.
- UNEXPLAINED: the writer's first focused run after H4 showed 1 failure it did
  not capture; the rerun passed. Possible flaky test or load-induced timeout
  (inferred, unproven). Re-check when memory allows, e.g. run the touched test
  files individually.
- Behaviour changes to remember: `applied.json` is no longer created on an
  empty corrections run; test for the old registry-reset behaviour was removed
  on purpose; ledger/registry corruption now raise (RegistryCorruptError,
  LedgerCorruptError).
- Route record: H1/H2/H4 delegated (writer).
- Native review (RDD) for the range c4567cba..06d77516: tier medium, 12 files,
  529 lines, user granted consent, lens review-reliability, outcome APPROVED and
  acknowledged (lineage review-d3c2f1a799715608, authority burned). Two
  non-blocking advisory findings became H9 and H10. The reviewer also stated
  the intermittent failure is not attributable to any visible change. Reviewed
  boundary is now 06d77516.

## Next step
H3 (API fails closed on routes without scope), after confirming the machine has
memory for focused test runs. H9 and H10 are cheap follow-ups to batch next.
