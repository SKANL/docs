# Reconcile documentation/runtime drift

## Objective

Make current public documentation, packaging entry points, traceability, and CI/QA claims agree with the behavior the repository actually executes.

## Authorization

The user authorized the architectural design and planning artifacts for all seven confirmed discrepancies. Production code, tests, configuration, test/build execution, commits, and remote operations are not authorized in this planning step.

## Problem and rationale

Current guidance contains seven confirmed mismatches with runtime or workflow evidence. Leaving them mixed together makes review and rollback difficult and encourages future changes to preserve ghost interfaces. The work is therefore split into seven behavior-oriented units, each pairing the relevant implementation or evidence with its tests and public documentation.

Architectural design: `docs/superpowers/specs/2026-09-27-reconcile-documentation-runtime-drift-design.md`.

## Scope and constraints

- Canonical evidence: `document_app` classify behavior; `tests/integration/test_ingest_roles_duplicates.py`; `pyproject.toml` entry points and local worker; `pipeline_service.FULL_STAGE_IDS`; `document_app` publication; `cli/main`; `api/app`, OpenAPI, and API tests; quality/toolchains workflows; render-verification adapter; real existing tests.
- Preserve unrelated `.atl/**` changes. Do not edit, restore, clean, stage, or commit them.
- Non-scope: remove unused `AtomicTransform` duplication or expand Redis, S3, or Playwright capabilities.
- Do not add compatibility commands or capabilities merely to make stale documentation true.
- Current `/v1` material may remain only as migration history in `docs/superpowers/specs/2026-09-21-api-v2-contract.md`.
- Authored changed-line budget is advisory per task and monitored cumulatively for delivery slicing; do not code-golf tests or documentation.

## Delivery and testing policy

- Delivery strategy: `ask-on-risk`.
- Chain strategy: unresolved; ask only if forecast or running authored changes exceed roughly 400 lines before the next commit.
- Effective TDD mode: disabled. Authoritative source: parent execution ruling (no active current TDD configuration).
- Exact test runner: `uv run pytest`; ordinary focused checks are required, with no RED/GREEN claims.
- DRIFT-01 pre-change worktree evidence: feature branch `codex/reconcile-doc-runtime-drift`; pre-existing untouched `.atl/**` paths: `.atl/.skill-registry.cache.json`, `.atl/skill-registry.md`.
- When TDD is enabled, behavior changes require observed RED -> GREEN -> REFACTOR. When disabled, focused functional checks remain mandatory.
- Every completed task requires a Conventional Commit work-unit commit on a feature branch, with tests and documentation alongside behavior and the commit identity recorded here.

## Tasks

- [x] **DRIFT-01 — Reconcile keyed classification confirmation.** Fixed `document_app` classify behavior for canonical keyed queues, added exact-path duplicate-basename regression coverage, and documented the real CLI confirmation flow. **Route:** delegated direct; preparation and writer triggers apply because code, tests, and docs must be read and changed together. **Evidence:** `uv run pytest tests/integration/test_ingest_roles_duplicates.py -q` — 15 passed; `uv run pytest tests/unit/test_agents_md_content.py -q` — 13 passed; keyed inspect/confirm CLI scenario — PASS; `git diff --check` — PASS. Rollback boundary: revert the Task 1 changes in `document_app.py`, its integration and contract tests, and the AGENTS classification paragraph; this restores legacy queue handling only. Review assessment: not run because receipt-driven development is user-owned and was not enabled. Work-unit commit: `fix(cli): update keyed classification entries`.
- [x] **DRIFT-02 — Wire the installed worker entry point.** Changed `docs-worker` to dispatch to `docs.local_worker:main`, retained `docs.workers.cli` as the dependency-injected library boundary, added declared-entry-point regression coverage, and documented the local SQLite/single-host boundary without claiming unshipped distributed support. **Route:** delegated direct; preparation and writer triggers apply across packaging, worker, tests, and docs. **Evidence:** `uv run pytest tests/unit/test_local_worker.py -k "packaged_docs_worker or declared_entry_point" -q` — 2 passed, 3 deselected; `uv run pytest tests/unit/test_local_worker.py tests/unit/workers -q` — 74 passed; `uv run docs-worker --help` — PASS (requires `--workspace-root`, supports bounded `--iterations`); `git diff --check` — PASS. Rollback boundary: revert the `docs-worker` script target, its packaging dispatch tests, and the worker deployment section; this restores only the previous installed worker boundary while preserving `docs.workers.cli`. Review assessment: not run because receipt-driven development is user-owned and was not enabled. Work-unit commit: `fix(worker): dispatch installed script locally`.
- [x] **DRIFT-03 — Correct lifecycle, output, and stage-order claims.** Added public-documentation contracts that preserve declared stage order without sorting, aligned the documented sequence with `pipeline_service.FULL_STAGE_IDS`, and replaced retired output guidance with verified build artifacts in `output/current/` and explicit package/publication artifacts in `output/release/`. **Route:** delegated direct; multiple runtime and documentation sources require bounded mapping plus writing. **Evidence:** RED: `uv run pytest tests/architecture/test_public_documentation.py tests/integration/test_pipeline_service.py -k "stage_order or output_contract" -q` — 2 failed (inverted AGENTS stage order and retired output paths); GREEN: `uv run pytest tests/architecture/test_public_documentation.py tests/integration/test_pipeline_service.py -q` — 31 passed; integration runtime scenario: `tests/integration/test_pipeline_service.py` validates the exported stage sequence and full service execution — PASS; structural searches for retired output paths and inverse stage ordering — no current claims; `git diff --check` — PASS. Rollback boundary: revert the public-documentation contract test, stage-order integration assertion, and lifecycle/output prose in AGENTS, README, architecture, pipeline, and runtime guide; this restores only the former documentation contract. Review assessment: not run because receipt-driven development is user-owned and was not enabled. Work-unit commit: `docs(pipeline): align lifecycle with runtime outputs`.
- [ ] **DRIFT-04 — Remove ghost flat-pipeline commands.** Remove public references to `pipeline ingest`, `pipeline prep`, `pipeline assemble`, and `pipeline all`; point to commands registered in `cli/main`; add command-surface regression coverage. **Route:** delegated direct; public-doc sweep and CLI tests cross multiple files. **Evidence:** focused test command/result, help-surface scenario/result, stale-command search, rollback boundary, commit identity.
- [ ] **DRIFT-05 — Make `/v2` the current public API.** Replace current `/v1` claims with `/v2`, retain `/v1` only in `docs/superpowers/specs/2026-09-21-api-v2-contract.md`, and verify against `api/app`, OpenAPI, and API tests. **Route:** delegated direct; API evidence and documentation must change as one unit. **Evidence:** focused API/doc consistency command/result, OpenAPI scenario/result, `/v1` allowlist search, rollback boundary, commit identity.
- [ ] **DRIFT-06 — Align CI and QA documentation.** Document the quality job, Python 3.11, 86% project coverage, 70% differential coverage, the absence of `doctor`/arbitrary-skip failure in toolchains, and conditional optional Playwright browser QA. **Route:** delegated direct; workflows, adapter evidence, tests, and docs span multiple files. **Evidence:** focused workflow-contract command/result, optional-browser-QA scenario/result or explicit N/A, rollback boundary, commit identity.
- [ ] **DRIFT-07 — Rebuild honest traceability.** Rebuild `docs/traceability.json` using only real tests/evidence and add validation that every referenced `file::test` exists and supports the stated claim. **Route:** delegated direct; traceability data, validator behavior, tests, and evidence review are inseparable. **Evidence:** focused validator command/result, traceability validation scenario/result, rollback boundary, commit identity.

## DRIFT-03 review correction

- Round 1 corrected lifecycle wording to be policy- and pipeline-dependent: only a publish-permitted full `document` build writes `output/current/`; `document-build` and `verify` do not publish; `release` invokes the full release-policy pipeline; direct package/publish use explicit destinations while the managed release pipeline uses `output/release/`. Strengthened the documentation contract against these distinctions. **Evidence:** `uv run pytest tests/architecture/test_public_documentation.py tests/integration/test_pipeline_service.py -q` — 31 passed; `git diff --check` — PASS. Rollback boundary: revert this correction's prose and strengthened assertions, retaining the original DRIFT-03 contract. Work-unit commit: `fix(docs): scope lifecycle output claims`.

## Acceptance criteria

- [ ] All seven discrepancies satisfy the acceptance criteria in the architectural design.
- [ ] Current public claims resolve to executable behavior, verified evidence, or an explicit accurate boundary.
- [ ] Every task records focused tests, runtime/CLI/API/workflow evidence as applicable, rollback boundary, assessed review outcome, and work-unit commit identity.
- [ ] Repository-wide stale-claim searches pass with only documented historical allowlists.
- [ ] The resolved full test command passes after the final work unit, or every failure is recorded without claiming completion.
- [ ] Unrelated `.atl` changes are unchanged.

## Expected checks

- Focused pytest commands selected from the touched test modules for each task; exact commands must be recorded by the implementation worker.
- Installed `docs-worker` smoke/dispatch scenario after DRIFT-02.
- CLI help and command-surface assertions after DRIFT-01, DRIFT-03, and DRIFT-04.
- API/OpenAPI version checks and an allowlisted repository search for `/v1` after DRIFT-05.
- Workflow/adapter contract checks after DRIFT-06.
- Traceability resolver and honesty validation after DRIFT-07.
- Markdown/JSON parsing, `git diff --check`, and the resolved full test command before close.

## Progress

- Planning artifacts authored; no production files, tests, configuration, or `.atl` files changed.
- No tests or builds run and no commits created, by scope.
- Completed tasks: 2/7 (DRIFT-01 and DRIFT-02 committed).

## Next step

Proceed with DRIFT-03 while preserving the DRIFT-01 and DRIFT-02 work-unit boundaries and unrelated `.atl/**` changes.
