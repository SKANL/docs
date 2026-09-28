# Reconcile documentation with the runtime contract

## Decision

Reconcile the public documentation and traceability evidence to the behavior that the runtime, tests, packaging metadata, and CI workflows actually expose. The runtime is authoritative unless a work unit explicitly fixes a confirmed runtime defect; prose must not preserve a contradicted interface for compatibility.

The change is delivered as seven reviewable work units. Each unit keeps behavior, tests, and its user-facing documentation together so that every commit can be verified and rolled back independently.

## Canonical sources of truth

| Contract area | Canonical evidence |
|---|---|
| Classification queue | `document_app` classify behavior and `tests/integration/test_ingest_roles_duplicates.py` |
| Worker command and boundary | `pyproject.toml` entry points and the local worker implementation |
| Build lifecycle and publication | `pipeline_service.FULL_STAGE_IDS` and `document_app` publication behavior |
| Public CLI surface | `cli/main` command registration and CLI help/command tests |
| HTTP API | `api/app`, generated OpenAPI, and API tests |
| CI and QA | Quality/toolchains workflow definitions and the render-verification adapter |
| Traceability | Existing executable tests and evidence that can be resolved to a real `file::test` node |

When prose conflicts with executable evidence, update the prose. When the confirmed defect is executable behavior, first characterize the intended contract with a failing test, then make the smallest runtime change and update the documentation in the same work unit.

## Scope

### Included

1. Correct keyed classification-queue behavior and document the supported CLI confirmation flow.
2. Make the installed `docs-worker` entry point execute the local worker and document its real SQLite, single-host boundary.
3. Replace stale lifecycle and output claims with `output/current` and `output/release`, explicit publish semantics, and the actual stage order.
4. Remove ghost flat-pipeline commands (`pipeline ingest`, `prep`, `assemble`, and `all`) from public documentation and test the advertised command surface.
5. Replace public API `/v1` claims with `/v2`; retain `/v1` only as migration history in `docs/superpowers/specs/2026-09-21-api-v2-contract.md`.
6. Reconcile CI and QA prose to the workflows: the quality job uses Python 3.11, project coverage is 86%, differential coverage is 70%, toolchains does not run `doctor` or fail arbitrary skips, and optional Playwright browser QA is conditional.
7. Rebuild `docs/traceability.json` from real tests/evidence and validate that every referenced `file::test` exists and that its claim is supportable.

### Not included

- Removing the unused `AtomicTransform` duplication.
- Expanding Redis, S3, or Playwright capabilities.
- Introducing compatibility aliases for undocumented pipeline commands.
- Changing API behavior beyond the already-established `/v2` contract.
- Treating optional tooling as mandatory where the workflows do not.

## Architecture

### Reconciliation rule

Each public claim must resolve to one of three forms:

1. **Executable contract:** a registered command, entry point, route, stage, or workflow condition.
2. **Verified evidence:** a test or generated contract proving the claim.
3. **Explicit boundary:** a documented limitation that matches the implementation.

Claims with none of these anchors are removed rather than rephrased speculatively. Historical contracts remain only in a clearly identified migration document and must not leak into current usage guidance.

### Work units

#### WU-01 — Classification queue identity

- Characterize duplicate/keyed queue behavior in `tests/integration/test_ingest_roles_duplicates.py`.
- Fix the classify path in `document_app` so confirmation updates the intended keyed entry without conflating same-named or duplicate sources.
- Replace hand-edit-only guidance with the supported CLI confirmation command and its exact accepted roles.
- Rollback boundary: classification implementation, focused tests, and classification documentation only.

#### WU-02 — Installed worker execution

- Correct the `docs-worker` packaging entry point so an installed invocation reaches the local worker implementation.
- Test the installed-entry-point dispatch rather than merely importing the worker module.
- Document the actual operating boundary: local SQLite state and a single host, with no Redis/S3/distributed guarantees.
- Rollback boundary: worker entry-point metadata, local-worker dispatch tests, and worker boundary prose.

#### WU-03 — Lifecycle, outputs, and stage order

- Derive the documented stage sequence from `pipeline_service.FULL_STAGE_IDS`.
- Describe verified build output under `output/current` and explicit publication/release output under `output/release`.
- State that build/verify and publish are distinct lifecycle transitions; neither implies the other.
- Add or update contract tests where documentation names directories or stage order.
- Rollback boundary: lifecycle/output documentation and its focused assertions.

#### WU-04 — Remove ghost pipeline commands

- Delete public references to `pipeline ingest`, `pipeline prep`, `pipeline assemble`, and `pipeline all`.
- Point users to commands that are actually registered by `cli/main`.
- Add command-surface tests so documentation cannot again advertise nonexistent flat-pipeline commands.
- Do not add aliases merely to make stale documentation true.
- Rollback boundary: CLI documentation and CLI-surface tests.

#### WU-05 — Current API version

- Make `/v2` the only current public API prefix in usage and reference documentation.
- Verify claims against `api/app`, OpenAPI output, and API tests.
- Keep `/v1` text only in `docs/superpowers/specs/2026-09-21-api-v2-contract.md` as migration history.
- Add a documentation/API consistency check that rejects current `/v1` claims outside that allowlisted history file.
- Rollback boundary: API-facing documentation and version-consistency tests.

#### WU-06 — CI and QA truth

- Align CI prose with the quality workflow: Python 3.11, 86% project coverage, and 70% differential coverage.
- State accurately that the toolchains workflow does not run `doctor` and does not fail arbitrary skipped optional checks.
- Describe Playwright browser QA as conditional on the optional environment/tooling required by the workflow and render-verification adapter.
- Add focused assertions for workflow/documentation constants or behavior where maintainable.
- Rollback boundary: CI/QA documentation and workflow-contract tests; workflow expansion is excluded.

#### WU-07 — Honest traceability

- Rebuild `docs/traceability.json` around resolvable tests and evidence only.
- Add validation that each `file::test` target names an existing file and an existing collected test.
- Validate that a traceability description does not overstate what the referenced test proves.
- Remove unverifiable mappings rather than replacing them with approximate references.
- Rollback boundary: traceability data, its validator, and validator tests.

## Delivery and sequencing

Implement WU-01 through WU-07 in order because later traceability must reference the final test surface. Each unit is one coherent work-unit commit with its tests and documentation. Delivery strategy is `ask-on-risk`: track authored additions plus deletions, and before the next commit would push the review slice above roughly 400 lines, ask the maintainer to select the chain strategy.

No implementation begins until the effective TDD mode, its authoritative source, and exact test runner are resolved. If TDD is enabled, every runtime or validation behavior change follows observed RED -> GREEN -> REFACTOR. Documentation-only edits still require structural checks and evidence readback.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Documentation is changed to match an accidental behavior | Require an executable source of truth and a focused characterization test before changing behavioral claims. |
| Fixing docs by adding compatibility aliases expands the product surface | Remove ghost claims; do not create commands or capabilities solely to preserve stale prose. |
| `/v1` history is mistaken for current guidance | Allow it only in the named migration-history spec and test the boundary. |
| Traceability becomes syntactically valid but semantically weak | Require both resolvable nodes and a bounded honesty review against the referenced test. |
| CI values drift again | Anchor prose checks to workflow definitions or shared constants where practical. |
| Seven units exceed a reviewable slice | Use work-unit commits, monitor authored line count, and apply `ask-on-risk` before crossing the delivery budget. |
| Unrelated `.atl` edits are overwritten | Exclude `.atl/**` from writes, staging, restoration, and cleanup. |

## Verification strategy

Each implementation worker must record the exact command and observed result. Expected checks are:

- Focused tests for the changed runtime or validator behavior in each work unit.
- CLI help/command-surface assertions for classification, worker, lifecycle, and removed ghost commands.
- API/OpenAPI assertions for the `/v2` public contract and the `/v1` history allowlist.
- Workflow-contract assertions for Python and coverage values plus conditional browser QA semantics.
- Traceability validation proving every `file::test` is resolvable and its claim is supportable.
- A repository-wide search confirming no current public prose retains the seven stale claims outside explicit allowlists.
- `git diff --check` and Markdown/JSON structural validation for every work unit.
- The repository's resolved full test command after all seven units.

Tests, builds, commits, and remote operations are deliberately not part of this design-authoring step.

## Acceptance criteria

- [ ] Keyed classification confirmation updates the correct queue item, with regression coverage and accurate CLI documentation.
- [ ] Installed `docs-worker` invokes the local worker; SQLite/single-host limitations are explicit and tested.
- [ ] Public lifecycle prose names `output/current`, `output/release`, explicit publish semantics, and the runtime stage order.
- [ ] Public docs advertise no ghost flat-pipeline commands, and command-surface tests guard the claim.
- [ ] Current API documentation uses `/v2`; `/v1` appears only in the named migration-history spec.
- [ ] CI/QA documentation matches the workflow and adapter facts listed in WU-06.
- [ ] `docs/traceability.json` contains only real, validated evidence references with honest claims.
- [ ] Every work unit carries focused verification evidence and an independent rollback boundary.
- [ ] Unrelated `.atl` changes remain untouched.

