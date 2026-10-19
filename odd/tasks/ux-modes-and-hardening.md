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
- [x] H3 (D) [59381a59] API fails closed: a registered route with no scope entry is denied;
      add a test that introspects every registered route and asserts a scope.
- [x] H4 (D) [b86c7272] corrections: persist each applied id as it is applied, atomically.
- [x] H5 (D) [ab63ca1f] Sidecar: validate Host header (loopback names only); align body
      limits (128 MB vs 120 MB); replace hardcoded cursor HMAC secret with a
      per-install secret.
- [x] H6 (D) [dc03af4a] java_on_path stops mutating os.environ (pass env to the subprocess).
- [x] H8 (D) [c60b20ba] application/revision.py (~L179) has the same read-modify-write
      ordering as corrections (revision-log.json append + .diff numbering by
      glob count, unlocked, non-atomic): make it atomic and collision-safe.
- [x] H9 (D) [abb150fd] From review R3-corrections-no-dir-create: prove that
      atomic_write_text creates missing parent directories (the explicit mkdir
      was removed from corrections.py and the repositories); add a test writing
      into a missing parent for corrections and each repository.
- [x] H10 (D) [95c2b1de] From review R3-ledger-stale-lock-test-weak: replace the removed
      competing-recoverer test with one covering a live-owner lock timing out,
      and pin the stale-lock test to explicit owner data instead of relying on
      owned_directory_lock internals.
- [x] H11 (I) [2d4b1671] Found while closing H10: `owned_directory_lock` release used
      rmtree(ignore_errors=True), which fails on Windows when a contender has
      owner.json open and orphaned the lock (26/30 contended trials). Release
      now retries; test_locking.py added (RED observed). This was the
      "unexplained intermittent failure" (concurrent provenance test).
- [x] H12 (D) [80838dfc] `_reclaim_stale` uses `os.kill(pid, 0)`, which on Windows reports
      an exited pid as alive, so a crashed owner's lock is never reclaimed.
      Use a real liveness check (OpenProcess/psutil-free) with a test.
- [x] H7 (D) [29b62f78] composition: hard imports (opendataloader_pdf, filetype, pypdfium2)
      become lazy with an actionable `doctor` message instead of killing the CLI.

### B. Cleanup and documentation truth
- [x] C1 (D) [8397bddc] Remove dead code with its tests: domain/models/result.py,
      RunRecorderService/RunHistoryService/RunReporter (+composition wiring),
      domain/pipeline.py legacy stage sets. Confirm no callers first.
- [x] H13 (D) [902f5db6] From review of batch 4 (approved, lineage review-ac887632da2641c9,
      acknowledged): (a) filetype_detector_adapter.detect() must not raise when
      `filetype` is missing (class contract says it never raises; fall back to
      extension detection); (b) revision diff numbering must not reuse a number
      after a diff file is removed (derive from log/max existing, not glob count);
      (c) RevisionService provenance_lock must be required, not a silent no-op
      default; `_record(**entry)` gets an explicit signature; (d) the interrupted
      log write test must fail only the LOG write (diff write succeeds) and the
      concurrency test must cover a gap; (e) locking: PermissionError is retried
      only for a short bounded grace (Windows mid-delete race), then raised as
      itself, not as a 30 s timeout; document the trade-off in a comment.
      Refuted in review (no action): R1-001/R3-005/R3-006 (commits exist, were
      outside the reviewed range), R1-002/R4-003/R3-007/R3-008 (rg shows no callers).
- [x] C2 (I) [ce86bb36] PluginRunner stays (tested sandbox) but docs state it is not wired
      into execution; no silent claim of plugin support.
- [x] C3 (D) [10aef688] Fix documented drift: AGENTS.md command-group table (no `docx`
      group; add source/document/workspace/run; `publish` under `document`),
      dangling sentence, ci.md missing test names and job count, CLAUDE.md
      (`pipeline <set>` commands, ARCHITECTURE_REQUIRE_GRAPH, toolchains skip
      gate claim, ruff scope, layout list). Keep test_agents_md_content green.
- [x] C4 (I) [4e0971b5] Lint `tools/` in CI (ruff scope) or document why not.

### C. UX: modes and information architecture
- [x] U1 (D) [870278c2] Mode state: `mode` (supervise|write) and `advanced` persisted per
      browser (try/catch localStorage), React context + tests.
- [x] U2 (D) [d7716796] Shell: topbar with workspace + document switcher, mode switch,
      Advanced toggle, theme toggle; remove "Review Studio foundation" footer.
- [x] U3 (D) [fc61fdc4] Navigation by mode/advanced (Supervisar: Inicio, Revisar, Entregar,
      Ejecuciones; Redactar adds Redactar; Avanzado adds Herramientas and
      Configuración técnica). Route map and palette follow the same rule.
- [x] U4 (D) [2d5eaa11] Home rewrite: what the product is, the 4-step flow, first-run mode
      chooser, one next action; distinguish "no workspace" from "no document";
      per-document (not workspace-wide) finding count.
- [x] U5 (D) [9f72e602] One vocabulary + in-context glossary; jargon (passport,
      attestation, digest, node ids) only under Avanzado.
- [x] U6 (D) [fa09a21a] Empty states always carry a next-step button.
- [x] U13 (D) [abae854d] From review of U4-U6 (approved, lineage review-c1e85141720fffe5,
      acknowledged): Home findings count must not fail open (findings without a
      run_id or outside the 100-run window are silently dropped: show a
      'partial count' notice or prefer a server-side document filter if the API
      supports it; do not claim 0 when unknown); Publications empty-state action
      only when document.publish is available; Spanish plural agreement for
      home.findings ('abierto/abiertos'); shared constants for focus-target ids;
      Advanced-only rows flagged structurally instead of matching the 'SHA-256'
      label; align wording 'open' vs status==='failed'.
- [x] U7 (D) [8cbc1dfc] Sections: primary actions (edit, save, review) vs advanced (stamp,
      pack context, build section); merge duplicate upload forms in Sources;
      single release entry point.
- [x] U8 (D) [98154674] Review: basic tabs (Findings, Artifacts, Compare) vs advanced
      (Evidence, Baselines, Quality, Graph).
- [x] U9 (D) [e1148967] Friendly error mapping with collapsible technical details.
- [x] U14 (D) From review of U13/U7-U9 (approved, lineage review-cb28abc3fa3a4fcb,
      acknowledged): Sources import must report partial success (do not Promise.all
      and lose already-stored files); clear the file input as well as state after
      an import so Ingest never sends an empty list; Import must stay available
      when document.import exists without source.ingest; SectionsPanel `editing`
      resets on section/mode/document change; PipelineLauncher policy resets when
      Advanced is turned off while 'release' is selected; friendly-error must not
      map a stale-chunk 'Failed to fetch dynamically imported module' TypeError to
      'service unreachable'; ErrorState message/error precedence made explicit in
      the type; status->kind mapping as a table; rename sectionsActions test file
      to match its scope.
- [x] U10 (D) i18n: dictionary layer, Spanish default + English, palette shows
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

Batch 2 (H3, H9, H10, H11): writer reported partial on one failing test,
test_concurrent_provenance_updates_merge_without_lost_runs; parent diagnosed it
as the lock-release bug above (H11), fixed it, and observed: test_locking +
test_provenance 23 passed, ruff clean, mypy clean, tests/architecture 131
passed, API+parity 471 passed (writer). Full suite NOT run.

Batch 3 (H12, H6, H5): writer complete; tests/architecture + 6 touched files
225 passed, ruff and mypy clean. Native review for 06d77516..ab63ca1f: tier high
(20 files, 574 lines), user DECLINED this candidate (no receipt). Reviewed
boundary stays 06d77516 conceptually; next assess uses base ab63ca1f.
Known limit: java_on_path swaps a module-level subprocess wrapper (not thread-safe).

Batch 4 (H8, H7, C1): writer complete; architecture 146 passed, ruff/mypy clean,
collect-only 3325 tests, no import errors. Also hardened locking.py (mid-delete
PermissionError retried). Spec files document-pipeline/document-render and
CLAUDE.md still mention removed pipeline_stage_plan / `pipeline <set>`: C3.
Native review for ab63ca1f..8397bddc: tier high (22 files, 600 lines), user
GRANTED, 4 lenses, lineage review-ac887632da2641c9 started. The bound STATUS
failed twice with operation_timeout ("aggregate time budget", mutation not
started, retry_safe false); not retried further. Review PENDING; lineage not
acknowledged. Retry when the machine is idle.

Batch 4 review closed: APPROVED and acknowledged (authority burned); 21
advisory findings triaged into H13 (real) or refuted by rg/commit history.
Batch 5 (C3, C2, C4): done, 151 tests + ruff + mypy green; drift guard test added.
Batch 6 (i18n base, U1, U2, U3): done (e85595dc, 870278c2, d7716796, fc61fdc4,
403ec87a); vitest files green individually, typecheck + lint clean. Known gaps:
Playwright e2e not updated (break under Spanish default / hidden Authoring);
palette capability items unfiltered (U10); Supervisar mode cannot reach Sources
upload from nav (solve in U4 via Home next-action, both modes).
Frontend baseline: 3 timing-flaky tests under load (pipelineFeature, reviewFeature,
toolsFeature), pre-existing.

Review of U4-U6 (base 902f5db6): the full range 8397bddc..HEAD (60 files, 1633
lines) was refused by the native reviewer (lens_context_budget_exceeded, no
authority created) and was split. U4-U6 slice (28 files, 628 lines): APPROVED and
acknowledged, 11 advisory findings -> U13. The earlier slice (C3/C2/C4 docs, i18n,
U1-U3, H13) cannot be isolated by a base-diff review (head is fixed at HEAD):
left unreviewed natively, covered by tests only. .atl/skill-registry files
modified by the session hook are unrelated and left uncommitted.

Batch 8 (U13, U7, U8, U9): done; typecheck + lint clean; vitest per-file green;
the full npm test showed 4 home.test failures at ~1.1 s each under load (passed
30/30 on its own right after), plus 2 known-flaky tests that passed on rerun.
Follow-ups: dialogs (ConfirmActionDialog, WorkspaceFormDialog, DocumentCreateDialog,
rename) and ApiStatus/DocumentStatusPanel/context switcher still use formatApiError
text; fold into U10 sweep. Mutation error toasts do not exist (ActionError covers).

Review of U13/U7-U9 (base fa09a21a, 35 files, 637 lines): APPROVED and
acknowledged; 11 advisory findings, 5+ real -> U14.

## Next step
U14 + U10 sweep, then U11, U12.

## U14 + U10 outcome
Commits b4094a68..1861b6f1 (hardening, palette labels, full i18n of all areas, literal-scan test).
Native review of the tail slice 5953072f..HEAD (24 files, 1084 lines): granted, APPROVED, 3 advisory
(publish policy label untested, doctor status text untested, literal guard blind to ternaries),
lineage review-0f91c3e969e429e5 acknowledged. Earlier i18n commits cannot be isolated by a base-diff
review (head fixed at HEAD, 4076 lines total exceed the lens budget): covered by tests only.
Reviewed boundary: 1861b6f1. Next: U11, U12.
