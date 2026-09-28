# Reconcile Documentation/Runtime Drift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make public documentation, packaging entry points, traceability, and CI/QA claims agree with the behavior the repository actually executes.

**Architecture:** Treat executable runtime surfaces and verified tests as authoritative, except for the two confirmed runtime defects fixed in Tasks 1 and 2. Deliver seven ordered work units; each unit couples behavior or evidence, focused tests, and user-facing documentation so it can be reviewed, committed, and rolled back independently.

**Tech Stack:** Python 3.11+, Typer, pytest, TOML packaging metadata, JSON, Markdown, GitHub Actions YAML.

**Spec:** `docs/superpowers/specs/2026-09-27-reconcile-documentation-runtime-drift-design.md`

## Global Constraints

- Before Task 1 changes any source, resolve the effective TDD mode, its authoritative source, and the exact test runner from existing project/session configuration or explicit user direction; do not infer TDD from the presence of tests and do not use SDD initialization.
- The commands below use the repository's current candidate prefix, `uv run pytest`. If the authoritative runner differs, update this plan and `odd/tasks/reconcile-documentation-runtime-drift.md` with the resolved mode/source/runner before executing any RED step.
- When TDD is enabled, every runtime or validator change must show observed RED -> GREEN -> REFACTOR. When disabled, run the same focused checks and record the result, but do not claim TDD evidence.
- Implement Tasks 1 through 7 in order. Task 7 depends on the final test surface established by Tasks 1 through 6.
- Each task is one reviewable work-unit commit with its tests and public documentation. Use Conventional Commit messages and record the commit ID, focused command/result, runtime scenario/result or explicit N/A, and rollback boundary in `odd/tasks/reconcile-documentation-runtime-drift.md`.
- Delivery strategy is `ask-on-risk`. Track authored additions plus deletions; before the next commit would push the accumulated review slice above roughly 400 lines, ask the maintainer to choose `stacked-to-main` or `feature-branch-chain`.
- Preserve unrelated `.atl/**` changes exactly. Never edit, restore, clean, stage, or commit `.atl/.skill-registry.cache.json`, `.atl/skill-registry.md`, or any other `.atl/**` path.
- Make no remote operation: no fetch, pull, push, PR creation, upload, or use of remote credentials/sessions.
- Do not remove `AtomicTransform`, expand Redis/S3/Playwright support, add compatibility aliases for ghost commands, or change API behavior beyond the established `/v2` contract.
- Current API documentation may mention `/v1` only in `docs/superpowers/specs/2026-09-21-api-v2-contract.md`, explicitly as migration history.
- Run `git diff --check` and parse changed Markdown/JSON after every task. Run the resolved full test command after Task 7.

## Review Focus

1. **Keyed classification queues:** a queue stored as `{"entries": {relative_path: entry}}` must update exactly the requested relative path, including same-basename files in different directories; Task 1 adds this regression case.
2. **Installed worker dispatch:** invoking the packaged `docs-worker` entry point must reach `docs.local_worker:main` and retain its required workspace boundary instead of the dependency-injected library CLI; Task 2 tests the declared script target and dispatch.
3. **Historical/current contract separation:** stale output paths, ghost commands, and `/v1` routes must not leak from historical documents into current guidance; Tasks 3-5 add allowlisted documentation-contract tests.
4. **Workflow optionality:** CI prose must not imply that `doctor`, skip-failure logic, or Playwright runs when the workflow does not provide them; Task 6 checks workflow facts and conditional browser-QA wording together.
5. **Traceability honesty:** syntactically valid references can still name missing or non-collected tests, or overclaim their assertions; Task 7 resolves every node ID through pytest collection and requires a bounded evidence review of each description.

---

### Task 1: Reconcile keyed classification confirmation

**Files:**
- Modify: `src/docs/cli/commands/document_app.py:464-488`
- Modify: `tests/integration/test_ingest_roles_duplicates.py`
- Modify: `tests/unit/test_agents_md_content.py`
- Modify: `AGENTS.md:284-302`
- Modify: `odd/tasks/reconcile-documentation-runtime-drift.md`

**Interfaces:**
- Consumes: canonical queue shape `{"schema": 1, "entries": {relative_path: entry}}` emitted by `IngestClassificationService.write_classification_queue`.
- Produces: `docs document classify --file <relative-path> --role <evidence|example|normative>` updates only `entries[relative_path]["confirmed_role"]`; JSON inspection still returns a stable `items` view.

- [ ] **Step 1: Record execution authority before the first source change**

Resolve and record `effective_tdd`, its authoritative source, and the exact test runner in `odd/tasks/reconcile-documentation-runtime-drift.md`. Confirm the worktree is on a feature branch and record the pre-existing `.atl/**` paths from `git status --short` without modifying them.

- [ ] **Step 2: Write the failing keyed-queue CLI regression tests**

Add tests named `test_document_classify_updates_the_requested_keyed_entry` and `test_document_classify_does_not_conflate_duplicate_basenames`. Assert that `normativa/shared.md` changes to `normative`, `examples/shared.md` remains unchanged, and invalid/missing paths still fail without rewriting the queue.

- [ ] **Step 3: Run the focused test to verify RED**

Run: `uv run pytest tests/integration/test_ingest_roles_duplicates.py -k "document_classify" -q`

Expected: FAIL because `document_app.classify` iterates the keyed `entries` mapping as if it were a list and cannot select the requested entry.

- [ ] **Step 4: Implement the minimum keyed-shape fix**

Update `classify(...) -> None` to recognize the canonical `entries` mapping, look up by exact relative-path key, preserve the queue envelope and unrelated entries, and project entries to the existing JSON response. Retain compatibility only for already-supported list/items/sources shapes; do not invent fuzzy basename matching.

- [ ] **Step 5: Run the focused test to verify GREEN and refactor safely**

Run: `uv run pytest tests/integration/test_ingest_roles_duplicates.py -q`

Expected: PASS, including existing queue determinism, round-trip, and invalid-role cases.

- [ ] **Step 6: Correct the public classification workflow and guard the claim**

Replace the hand-edit-only guidance in `AGENTS.md` with the exact `docs document classify --file ... --role ...` flow and accepted roles. Add `test_documents_classification_uses_the_registered_confirmation_command` in `tests/unit/test_agents_md_content.py`; it must require the command and reject the old "no CLI command" claim.

- [ ] **Step 7: Verify, update recovery evidence, and commit the work unit**

Run the focused tests, `git diff --check`, and a CLI scenario that inspects then confirms a keyed entry. Update DRIFT-01 evidence and rollback boundary, stage only the files above, verify `.atl/**` is unstaged, then commit:

```bash
git commit -m "fix(cli): update keyed classification entries"
```

Review focus: exact-key selection, envelope preservation, duplicate basenames, and no undocumented accepted roles.

### Task 2: Wire the installed local worker

**Files:**
- Modify: `pyproject.toml:35-40`
- Modify: `tests/unit/test_local_worker.py`
- Modify: `docs/deployment.md:68-80`
- Modify: `odd/tasks/reconcile-documentation-runtime-drift.md`

**Interfaces:**
- Consumes: `docs.local_worker.main(argv: list[str] | None = None) -> int` and its required `--workspace-root` plus bounded `--iterations` options.
- Produces: installed script `docs-worker = "docs.local_worker:main"`; documented SQLite state at `<workspace>/.docs/x20.sqlite3` and single-host-only operating boundary.

- [ ] **Step 1: Write the failing installed-entry-point contract test**

Add `test_packaged_docs_worker_targets_local_worker` to parse `pyproject.toml` with `tomllib` and assert `[project.scripts]["docs-worker"] == "docs.local_worker:main"`. Add a dispatch test that monkeypatches `docs.local_worker.main`, resolves the declared `module:function`, invokes it, and proves the declared entry point reaches the local worker callable.

- [ ] **Step 2: Run the entry-point tests to verify RED**

Run: `uv run pytest tests/unit/test_local_worker.py -k "packaged_docs_worker or declared_entry_point" -q`

Expected: FAIL because the package currently points to `docs.workers.cli:main`, which requires an injected service factory and is not the local executable.

- [ ] **Step 3: Change only the packaging entry point**

Set `docs-worker = "docs.local_worker:main"`. Do not delete or repurpose `docs.workers.cli`; it remains a dependency-injected library boundary with separate tests.

- [ ] **Step 4: Run local-worker and worker-library tests to verify GREEN**

Run: `uv run pytest tests/unit/test_local_worker.py tests/unit/workers -q`

Expected: PASS; local entry-point tests reach `docs.local_worker`, and dependency-injected worker tests remain intact.

- [ ] **Step 5: Replace distributed deployment claims with the executable boundary**

Update `docs/deployment.md` to show `docs-worker --workspace-root <path> [--iterations N]`, local SQLite state, and a single-host boundary. Remove instructions that claim the shipped entry point provides Redis, S3/blob, multi-host queue, lease, or distributed-worker guarantees.

- [ ] **Step 6: Verify, update recovery evidence, and commit the work unit**

Run the focused tests, `git diff --check`, and `uv run docs-worker --help` (or the exact equivalent produced by the resolved environment). Update DRIFT-02 evidence and rollback boundary, stage only Task 2 files, verify `.atl/**` is unstaged, then commit:

```bash
git commit -m "fix(worker): dispatch installed script locally"
```

Review focus: the script target, preservation of the injectable worker module, and documentation that does not imply unshipped distributed guarantees.

### Task 3: Correct lifecycle, output, and stage-order claims

**Files:**
- Create: `tests/architecture/test_public_documentation.py`
- Modify: `tests/integration/test_pipeline_service.py`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/pipeline.md`
- Modify: `docs/runtime-guide.md`
- Modify: `odd/tasks/reconcile-documentation-runtime-drift.md`

**Interfaces:**
- Consumes: `src.docs.application.pipeline_service.FULL_STAGE_IDS`, `document_app` artifact destinations, and package/publication behavior.
- Produces: current docs consistently distinguish verified build output `output/current/`, explicit package/release output `output/release/`, and separate publish semantics; documented stage order exactly equals `FULL_STAGE_IDS`.

- [ ] **Step 1: Write failing documentation-contract tests**

In `tests/architecture/test_public_documentation.py`, add helpers that read the current public-doc allowlist and extract the declared stage list. Add tests `test_public_stage_order_matches_full_stage_ids` and `test_current_docs_use_current_and_release_output_contract`; assert exact tuple equality and reject legacy claims that `document publish` snapshots `output/work/` into `output/published/`.

- [ ] **Step 2: Run the contract tests to verify RED**

Run: `uv run pytest tests/architecture/test_public_documentation.py tests/integration/test_pipeline_service.py -k "stage_order or output_contract" -q`

Expected: FAIL on the README stage-order inversion and legacy lifecycle/output claims in current documentation.

- [ ] **Step 3: Reconcile lifecycle and outputs without changing runtime behavior**

Update the listed documents so `FULL_STAGE_IDS` ends `record-provenance -> package-release -> publish-draft`, verified build artifacts are under `output/current/`, release/package artifacts are under `output/release/`, and build/verify/publish remain distinct transitions. Remove contradictory `output/work/`/`output/published/` lifecycle guidance rather than reviving retired behavior.

- [ ] **Step 4: Run focused runtime and docs-contract tests to verify GREEN**

Run: `uv run pytest tests/architecture/test_public_documentation.py tests/integration/test_pipeline_service.py -q`

Expected: PASS with documentation-derived stage order equal to `FULL_STAGE_IDS` and no legacy current-output claim.

- [ ] **Step 5: Structurally read back every changed claim**

Search current docs for `output/work`, `output/published`, and both possible orderings of `package-release`/`publish-draft`. Classify any remaining mention as current truth or remove it; historical design files are not rewritten in this task.

- [ ] **Step 6: Update recovery evidence and commit the work unit**

Run `git diff --check`, update DRIFT-03 evidence and rollback boundary, stage only Task 3 files, verify `.atl/**` is unstaged, then commit:

```bash
git commit -m "docs(pipeline): align lifecycle with runtime outputs"
```

Review focus: stage-order extraction must not silently sort, and output-directory assertions must distinguish current build artifacts from explicit release artifacts.

### Task 4: Remove ghost flat-pipeline commands

**Files:**
- Modify: `docs/pipeline.md:1-45`
- Modify: `tests/integration/test_cli_composition_root.py`
- Modify: `tests/architecture/test_public_documentation.py`
- Modify: `odd/tasks/reconcile-documentation-runtime-drift.md`

**Interfaces:**
- Consumes: command registration exposed by `docs.cli.main.app` and its Typer command tree.
- Produces: public guidance uses only registered commands such as `source ingest`, `document ingest`, `document prepare`, `document build`, and `document release`; no compatibility aliases are added.

- [ ] **Step 1: Write the failing ghost-command documentation test**

Add `test_current_docs_do_not_advertise_ghost_pipeline_commands`, checking current public docs for `pipeline ingest`, `pipeline prep`, `pipeline prepare`, `pipeline assemble`, and `pipeline all`. Extend the root command-surface characterization only as needed to prove there is no `pipeline` group.

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `uv run pytest tests/architecture/test_public_documentation.py tests/integration/test_cli_composition_root.py -k "ghost_pipeline or command_surface" -q`

Expected: FAIL because `docs/pipeline.md` advertises flat pipeline routes absent from `cli/main`.

- [ ] **Step 3: Replace ghost instructions with registered commands**

Rewrite the source-preparation section of `docs/pipeline.md` around `document ingest`/`document prepare` and the registered public stage-backed boundaries. Do not add a `pipeline` Typer group or aliases.

- [ ] **Step 4: Run the CLI/docs contract to verify GREEN**

Run: `uv run pytest tests/architecture/test_public_documentation.py tests/integration/test_cli_composition_root.py tests/unit/test_agents_md_content.py -q`

Expected: PASS; the documentation mentions no ghost command and the command tree is unchanged.

- [ ] **Step 5: Verify, update recovery evidence, and commit the work unit**

Run a repository search for the five ghost phrases, allow only the approved design/plan text describing their removal, run `git diff --check`, update DRIFT-04 evidence and rollback boundary, stage only Task 4 files, verify `.atl/**` is unstaged, then commit:

```bash
git commit -m "docs(cli): remove ghost pipeline commands"
```

Review focus: no regex false positives from the design history and no runtime surface growth to accommodate stale prose.

### Task 5: Make `/v2` the only current public API

**Files:**
- Modify: `docs/api-transport.md`
- Modify: `docs/deployment.md`
- Modify: `docs/plugins.md`
- Modify: `tests/unit/api/test_application.py`
- Modify: `tests/unit/api/test_openapi.py`
- Modify: `tests/architecture/test_public_documentation.py`
- Modify: `odd/tasks/reconcile-documentation-runtime-drift.md`

**Interfaces:**
- Consumes: routes registered by `src/docs/api/application.py` and paths generated by `src/docs/api/openapi.py`.
- Produces: all current usage/reference prose uses `/v2`; `/v1` route prose is allowed only in `docs/superpowers/specs/2026-09-21-api-v2-contract.md` as migration history.

- [ ] **Step 1: Write failing API/document consistency tests**

Add `test_current_api_docs_use_only_v2_routes` to scan `README.md`, `AGENTS.md`, and current top-level `docs/*.md`; planning/spec artifacts under `docs/superpowers/**` are not current usage guidance. Assert every documented current route prefix exists in generated OpenAPI, `/v2/openapi.json` is live, and `/v1/openapi.json` returns 404. Independently assert that the named migration-history spec remains the only allowlisted historical API-contract source.

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `uv run pytest tests/architecture/test_public_documentation.py tests/unit/api/test_application.py tests/unit/api/test_openapi.py -k "api_docs or openapi or v1" -q`

Expected: FAIL on `/v1` usage in `docs/api-transport.md`, `docs/deployment.md`, and `docs/plugins.md`.

- [ ] **Step 3: Reconcile current API prose with generated `/v2` paths**

Replace current `/v1` examples, route lists, SSE guidance, and plugin endpoints with exact `/v2` paths verified in OpenAPI. Leave the named migration-history spec unchanged and do not add `/v1` aliases.

- [ ] **Step 4: Run API and docs-contract tests to verify GREEN**

Run: `uv run pytest tests/architecture/test_public_documentation.py tests/unit/api/test_application.py tests/unit/api/test_openapi.py -q`

Expected: PASS; current docs use only `/v2`, the history allowlist remains explicit, and runtime still rejects `/v1`.

- [ ] **Step 5: Verify, update recovery evidence, and commit the work unit**

Search Markdown for API-route-shaped `/v1/` strings, confirm the sole allowed file, run `git diff --check`, update DRIFT-05 evidence and rollback boundary, stage only Task 5 files, verify `.atl/**` is unstaged, then commit:

```bash
git commit -m "docs(api): publish only the v2 route contract"
```

Review focus: distinguish API route prefixes from unrelated schema strings such as `docs.x20/v1`, and do not rewrite the approved migration-history document.

### Task 6: Align CI and QA prose with workflows

**Files:**
- Modify: `docs/ci.md`
- Modify: `docs/qa.md`
- Modify: `tests/architecture/test_github_workflows.py`
- Modify: `tests/architecture/test_public_documentation.py`
- Modify: `odd/tasks/reconcile-documentation-runtime-drift.md`

**Interfaces:**
- Consumes: `.github/workflows/quality.yml`, `.github/workflows/toolchains.yml`, and `src/docs/infrastructure/verification/render_verification_adapter.py`.
- Produces: documentation names job `quality`, Python 3.11, project coverage 86%, differential coverage 70%, no toolchains `doctor`/arbitrary-skip gate, and conditional optional Playwright browser QA.

- [ ] **Step 1: Write failing workflow/documentation contract tests**

Add tests that parse or narrowly inspect the two workflow files and compare their facts with `docs/ci.md`/`docs/qa.md`: `uv python install 3.11`, `--cov-fail-under=86`, `diff-cover ... --fail-under=70`, job name `quality`, absence of a `docs doctor` toolchains step, and absence of arbitrary skip-failure logic. Add a test requiring QA prose to describe Playwright browser checks as conditional/optional, not guaranteed.

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `uv run pytest tests/architecture/test_github_workflows.py tests/architecture/test_public_documentation.py -k "coverage or toolchains or playwright or quality_job" -q`

Expected: FAIL because `docs/ci.md` names a nonexistent `check` job, claims 93% coverage and toolchains behavior that is not in the workflow, while `docs/qa.md` repeats the stale floor and browser boundary.

- [ ] **Step 3: Rewrite CI and QA claims from workflow evidence**

Update `docs/ci.md` and `docs/qa.md` with the exact facts above. Explain that Playwright browser QA runs only when the optional environment/package/browser capability is present; do not expand the workflow or make optional checks mandatory.

- [ ] **Step 4: Run workflow and docs-contract tests to verify GREEN**

Run: `uv run pytest tests/architecture/test_github_workflows.py tests/architecture/test_public_documentation.py tests/unit/infrastructure/test_html_browser_qa.py -q`

Expected: PASS; prose and workflows agree, and optional browser behavior remains graceful.

- [ ] **Step 5: Verify, update recovery evidence, and commit the work unit**

Search current CI/QA docs for `93`, job `check`, unconditional `doctor`, and unconditional Playwright language. Run `git diff --check`, update DRIFT-06 evidence and rollback boundary, stage only Task 6 files, verify `.atl/**` is unstaged, then commit:

```bash
git commit -m "docs(ci): align quality claims with workflows"
```

Review focus: tests should anchor stable contract facts without duplicating the entire YAML file, and optional tooling must remain optional.

### Task 7: Rebuild honest traceability

**Files:**
- Create: `tools/validate_traceability.py`
- Create: `tests/architecture/test_traceability.py`
- Modify: `docs/traceability.json`
- Modify: `docs/pipeline.md:55-78`
- Modify: `odd/tasks/reconcile-documentation-runtime-drift.md`

**Interfaces:**
- Consumes: traceability JSON strings shaped as `tests/...py::test_name`, repository files, and pytest collection output for referenced test files.
- Produces: `collect_test_nodeids(repo_root: Path, test_files: Collection[Path]) -> frozenset[str]` and `validate_traceability(payload: Mapping[str, object], repo_root: Path, collected_nodeids: Collection[str]) -> tuple[str, ...]`; the script entry point exits non-zero on unresolved evidence.

- [ ] **Step 1: Write failing validator unit/architecture tests**

Add tests for: missing file, missing test function, non-collected node ID, parameterized node IDs normalized to their base `file::test`, duplicate/empty evidence, and the real `docs/traceability.json`. The real-file test must gather pytest collection for referenced files and assert the validator returns no errors.

- [ ] **Step 2: Run validator tests to verify RED**

Run: `uv run pytest tests/architecture/test_traceability.py -q`

Expected: FAIL because no validator exists and current traceability references missing modules such as `tests/integration/test_v2_end_to_end.py` and `tests/integration/test_v2_real_toolchain_journey.py`.

- [ ] **Step 3: Implement the minimum deterministic validator**

Implement recursive extraction of fields named `test`, accept only repository-relative `tests/**/*.py::test_*` evidence, reject traversal/absolute paths, collect only the referenced files through pytest's collection mode, compare exact normalized node IDs with collected tests, and return sorted errors. Keep claim-support judgment out of the algorithm; semantic honesty remains a bounded reviewer step backed by the referenced assertions.

- [ ] **Step 4: Run synthetic validator cases to verify GREEN**

Run: `uv run pytest tests/architecture/test_traceability.py -k "missing or collected or parameterized or traversal" -q`

Expected: PASS for valid node IDs and deterministic failures for malformed or unresolved evidence.

- [ ] **Step 5: Rebuild traceability from the final real test surface**

Replace missing/approximate entries in `docs/traceability.json` with tests that actually exist after Tasks 1-6. Remove claims that have no defensible test rather than pointing to a nearby test. For every retained description, read the referenced assertions and narrow the prose to what they prove.

- [ ] **Step 6: Verify the real traceability file and documentation**

Run: `uv run pytest tests/architecture/test_traceability.py -q`

Expected: PASS; every `file::test` resolves through pytest collection. Update `docs/pipeline.md` to explain resolvable evidence and the semantic-review boundary without claiming the validator can infer proof from prose.

- [ ] **Step 7: Run final repository checks**

Run the resolved full test command, the seven stale-claim searches, JSON parsing for `docs/traceability.json`, Markdown structural readback, and `git diff --check`. Record every pass/failure/skip honestly; a failed or unavailable required check leaves DRIFT-07 incomplete.

- [ ] **Step 8: Update recovery evidence and commit the work unit**

Update DRIFT-07 evidence, cumulative authored line count, rollback boundary, and final acceptance checklist. Stage only Task 7 files, verify `.atl/**` is unstaged and unchanged, then commit:

```bash
git commit -m "test(traceability): validate executable evidence"
```

Review focus: recursive evidence extraction, node-ID normalization, collection failures, evidence descriptions that overstate assertions, and removal rather than approximation of unsupported mappings.

## Final handoff

- Confirm seven work-unit commit IDs and verification records are present in `odd/tasks/reconcile-documentation-runtime-drift.md`.
- Confirm `.atl/.skill-registry.cache.json` and `.atl/skill-registry.md` still appear only as the unrelated pre-existing changes and were never staged.
- Report the resolved TDD mode/source/runner, focused and full-test outcomes, cumulative authored line count, delivery-slice decision, and any remaining risk.
- Do not push, open a pull request, or otherwise perform remote operations without a separate explicit authorization.
