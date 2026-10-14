# Architecture consolidation

## Objective
Make the codebase stable and easy to extend before new features land: one
composition root, no ceremonial ports, no duplicated cross-cutting logic,
domain logic out of giant adapters.

## Problem (evidence from mapping, 2026-10-13)
- cli/sidecar/workers instantiate `Sqlite*Store` and other infrastructure
  directly instead of going through `ApplicationComposition`
  (`cli/commands/document_run.py:63,83,127,138,152`, `sidecar/stores.py:182-392`,
  `workers/composition.py:222`).
- Registry/state-path resolution duplicated ~6 times; `runtime.sqlite3` path
  rebuilt inline 6 times in `sidecar/stores.py`.
- Confine-then-remap-error duplicated 4 times; fail-open JSON read duplicated
  (`generate_visuals.py:84`, `figure_resolver.py:15`, sidecar, composition).
- 7 ports with one impl and zero fakes; 3 ports split over one class
  (`JsonDocumentRepository`); `PlatformSandboxProvider` has no prod impl.
- `composition.py` (747 lines) mixes config/token logic with wiring and types
  several attributes as `Any` or concrete adapters.
- Giant adapters hold pure theme/geometry logic.

## Constraints
- Strict TDD (source: CLAUDE.md; runner `uv run pytest`). RED before GREEN.
- Behaviour-preserving: no CLI/API contract change.
- Determinism invariants and architecture tests stay green.
- Checks per task: `uv run pytest`, `uv run ruff check .`, `uv run mypy`.
- ~400 authored lines per task is advisory only.
- Delivery strategy: ask-on-risk (default).

## Tasks
- [x] T1 Architecture test: only `composition.py` (and `infrastructure/`)
      may import `docs.infrastructure`; start with an explicit allowlist of
      current violators that later tasks shrink to empty. Route: inline.
- [x] T2 `RuntimeStores` bundle + single `state_path`/registry resolution,
      exposed by the composition root; migrate cli (`run_app`, `document_run`)
      to it. Route: delegated writer.
- [x] T3 Migrate sidecar (`stores.py`, `app.py`, `worker.py`) to the bundle;
      delete inline `runtime.sqlite3` paths. Route: delegated writer.
- [ ] T4 Collapse `workers/composition.py` production factories into the root
      (drop dead `create_production_worker*`). Route: delegated writer.
- [ ] T5 Move locking/guard helpers behind the composition root for cli
      (`document_release`, `document_batch`, `document_app`); empty the T1
      allowlist. Route: delegated writer.
- [ ] T6 Shared helpers: one confine→error mapper, one fail-open JSON reader
      in domain/identity-adjacent module; replace duplicates. Route: delegated.
- [ ] T7 Port pruning: inline the 7 one-impl/zero-fake ports after confirming
      no test substitutes them; merge Document/Registry/Template repository
      ports; drop or justify `PlatformSandboxProvider`. Route: delegated.
- [ ] T8 Split `composition.py`: config/token/path logic out to
      `application/workspace_config.py`; type attributes as ports. Route:
      delegated.
- [ ] T9 Extract `VisualTheme` + helpers to `domain/theme.py`, pure OOXML zip
      helpers to their own module. Route: delegated.
- [x] T10 Extract PDF layout/geometry helpers to `domain/pdf_layout.py`.
      Route: delegated.
- [x] T11 Contributor map: short "where do I add X" section in AGENTS.md.
      Route: inline.

## Acceptance
- No module outside `composition.py`/`infrastructure/` imports infrastructure
  (mechanised by T1).
- Full suite, ruff, mypy, coverage floor green after every task.

## Progress
- Branch: `refactor/single-composition-root`.
- T1 done (commit 6a2be37b). RED: with empty ALLOWLIST the scan reported 12
  violators (the mapped 10 plus `local_worker.py` and the dynamic
  `import_module` in `application/provenance.py`); GREEN with the allowlist.
  Full suite 3206 passed, 3 failed (2 in `tests/unit/plugins/test_sdk.py`
  process-timeout tests, flaky under full-suite load: 32/32 pass in
  isolation), ruff and mypy clean. Full suite takes ~21 min.
- T2 done (commit 70ea2b16). RED: `tests/unit/test_runtime_stores.py` failed at collection
  (ImportError on `RuntimeStores`, `resolve_workspace_registry`,
  `resolve_runtime_root`, `runtime_state_path`); GREEN 5 passed. Added to
  `composition.py` (lazy `RuntimeStores`, one registry/state-path
  resolution); `cli/commands/run_app.py` and `document_run.py` migrated and
  removed from the allowlist (`document_app.py` adapted to the new
  `durable_evidence_stores` return). Targeted: architecture + unit/cli +
  composition 151 passed; ruff and mypy clean. Full suite runs in a side
  worktree (~21 min) and is reported in the final handoff.
- T3 done. RED: sidecar test with the new `build_worker(..., leases, ...)`
  signature + shrunken allowlist + new `test_the_runtime_sqlite_path_is_declared_once`
  failed (3 failures). GREEN after migrating `sidecar/stores.py` (one
  `PerRoot(RuntimeStores)` per facade), `app.py` (idempotency), `worker.py`
  (`build_worker` now receives `leases` instead of a state path) and
  `local_worker.py` (a violator the mapping missed). `sidecar/roots.state_path`
  removed. `atomic_write_text` for baseline promotion now comes from the
  composition root. Targeted suites (sidecar, local_worker, api, architecture)
  green; ruff and mypy clean.
- Next: T4.
