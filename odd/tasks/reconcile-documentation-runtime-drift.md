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
- Effective TDD mode: unresolved, but its source is required before implementation. Resolve it from existing project/session configuration or an explicit user choice; do not infer it from the presence of tests and do not use SDD initialization.
- Exact test runner: unresolved with the TDD source. Record both before the first implementation delegation.
- When TDD is enabled, behavior changes require observed RED -> GREEN -> REFACTOR. When disabled, focused functional checks remain mandatory.
- Every completed task requires a Conventional Commit work-unit commit on a feature branch, with tests and documentation alongside behavior and the commit identity recorded here.

## Tasks

- [ ] **DRIFT-01 — Reconcile keyed classification confirmation.** Fix `document_app` classify keyed-queue behavior, add regression coverage in `tests/integration/test_ingest_roles_duplicates.py`, and document the real CLI confirmation flow. **Route:** delegated direct; preparation and writer triggers apply because code, tests, and docs must be read and changed together. **Evidence:** focused test command/result, CLI scenario/result, rollback boundary, commit identity.
- [ ] **DRIFT-02 — Wire the installed worker entry point.** Make the installed `docs-worker` entry point execute the local worker, test installed dispatch, and document the SQLite/single-host boundary without implying Redis/S3 or distributed support. **Route:** delegated direct; preparation and writer triggers apply across packaging, worker, tests, and docs. **Evidence:** focused test command/result, installed-entry-point scenario/result, rollback boundary, commit identity.
- [ ] **DRIFT-03 — Correct lifecycle, output, and stage-order claims.** Replace stale output paths with `output/current` and `output/release`, state explicit publish semantics, and document the order from `pipeline_service.FULL_STAGE_IDS` and `document_app` publication behavior. **Route:** delegated direct; multiple runtime and documentation sources require bounded mapping plus writing. **Evidence:** focused assertions/result, lifecycle scenario/result, rollback boundary, commit identity.
- [ ] **DRIFT-04 — Remove ghost flat-pipeline commands.** Remove public references to `pipeline ingest`, `pipeline prep`, `pipeline assemble`, and `pipeline all`; point to commands registered in `cli/main`; add command-surface regression coverage. **Route:** delegated direct; public-doc sweep and CLI tests cross multiple files. **Evidence:** focused test command/result, help-surface scenario/result, stale-command search, rollback boundary, commit identity.
- [ ] **DRIFT-05 — Make `/v2` the current public API.** Replace current `/v1` claims with `/v2`, retain `/v1` only in `docs/superpowers/specs/2026-09-21-api-v2-contract.md`, and verify against `api/app`, OpenAPI, and API tests. **Route:** delegated direct; API evidence and documentation must change as one unit. **Evidence:** focused API/doc consistency command/result, OpenAPI scenario/result, `/v1` allowlist search, rollback boundary, commit identity.
- [ ] **DRIFT-06 — Align CI and QA documentation.** Document the quality job, Python 3.11, 86% project coverage, 70% differential coverage, the absence of `doctor`/arbitrary-skip failure in toolchains, and conditional optional Playwright browser QA. **Route:** delegated direct; workflows, adapter evidence, tests, and docs span multiple files. **Evidence:** focused workflow-contract command/result, optional-browser-QA scenario/result or explicit N/A, rollback boundary, commit identity.
- [ ] **DRIFT-07 — Rebuild honest traceability.** Rebuild `docs/traceability.json` using only real tests/evidence and add validation that every referenced `file::test` exists and supports the stated claim. **Route:** delegated direct; traceability data, validator behavior, tests, and evidence review are inseparable. **Evidence:** focused validator command/result, traceability validation scenario/result, rollback boundary, commit identity.

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
- Completed tasks: 0/7.

## Next step

Resolve the effective TDD mode, its authoritative source, and the exact test runner. Then delegate DRIFT-01 on a feature branch, keeping its code, regression test, documentation, verification, and rollback evidence in one work-unit commit.
