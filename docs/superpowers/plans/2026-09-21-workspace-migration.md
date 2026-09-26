# Canonical Workspace and Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce one versioned canonical workspace format and a recoverable, explicit one-way migration from supported existing formats.

**Architecture:** Keep author-editable content in files under one registered workspace root; `documents/` and `templates/` are descendants of that root. Migration is an offline boundary tool that detects, reports, converts beside a separate destination, validates, and publishes atomically without changing or deleting the source. Explicit registry/config selection is the later cutover. Normal runtime accepts only the strict canonical marker. External config/global registry, generated delivery output, and operational X20 state follow the boundaries below.

**Tech Stack:** Python 3.11+, Pydantic/current schema validators, filesystem adapters, pytest, JSON fixtures.

**Spec:** `docs/superpowers/specs/2026-09-21-canonical-repository-design.md`

## Global Constraints

- Preserve authored content, source identity, assets, references, hashes, required metadata, and provenance evidence through supported migrations.
- The canonical marker is exactly `<workspace-root>/workspace.json` containing only `{"schema":"docs.workspace/v1"}`. Reject duplicate keys, unknown fields, missing/malformed values, and unsupported versions before reads or writes.
- Ordinary runtime accepts one registered root only. `documents/` and `templates/` must be descendants; split-root configuration is legacy migration input only and is retired after cutover.
- Do not dual-read or dual-write historical formats in ordinary runtime; old-format support belongs only to migration.
- Keep editable workspace files separate from transactional operational state.
- Migration must be idempotent for canonical workspaces, fail closed for unsupported/ambiguous input, publish only to a new separate destination, and leave the recoverable source untouched until and after explicit cutover.
- Migration does not modify `docs.config.json`, the global workspace registry, or X20/sidecar operational state.
- Preserve authored, behavior-affecting, and evidence-bearing records. Omit and report rebuildable rendered outputs/packages/QA previews/caches; reject unknown records rather than silently copying them.
- Do not overwrite, reformat, or absorb pre-existing user changes.

## Review Focus

- Ambiguous or malformed version/config fields must stop before writes; test no mutation.
- Symlink/path traversal and destination-inside-source cases must not escape selected roots; test adversarial paths.
- Mid-conversion validation failure must preserve the source and remove/retain scratch according to documented recovery policy; test injected failure.
- An existing destination is always refused. There is no force/replace path in the v1 migration.
- Before publication failure removes safe scratch state; failed cleanup reports the exact non-workspace scratch path. After publication, recovery keeps or deletes the unselected destination; after explicit cutover, rollback reselects the unchanged source.
- Duplicate assets, broken references, and unusual authored bytes must be reported without silent loss; use representative fixture tests.

## File Map

| Path | Responsibility in this plan |
|---|---|
| `src/docs/application/workspaces.py` | Workspace registry/use cases; distinguish registry metadata and configured root paths from workspace content. |
| `src/docs/infrastructure/persistence/json_repository.py`, `json_context_repository.py`, `json_section_repository.py`, `filesystem_asset_repository.py` | Current JSON/context/section/asset persistence adapters; canonical content reader/writer and safe publication work. |
| `src/docs/application/imports.py` | Staged source imports; preserve source identity and deduplication semantics. |
| `src/docs/cli/commands/workspace_app.py` | Workspace command group; owner for proposed `docs workspace migrate`. |
| `src/docs/cli/commands/doc_app.py`, `context_app.py`, `document_app.py` | Document/context commands that must reject noncanonical workspaces in normal runtime. |
| `src/docs/api/application.py` | API workspace selection/read/write behavior. |
| `tests/unit/` and `tests/integration/` workspace/document/context/import/persistence test modules named in Task 1 | Characterize each current schema and migration behavior. |
| `docs/superpowers/specs/2026-09-21-workspace-format-inventory.md` | Task 1 decision record for source formats and canonical scope. |
| `README.md`, `docs/architecture.md`, `docs/pipeline.md`, `AGENTS.md` | Document canonical schema and recovery/migration operations. |

## Tasks

### Task 1: Census persisted formats and establish fixtures

**Files:**
- Test: `tests/unit/application/test_workspaces.py`, `tests/unit/domain/test_workspace.py`, `tests/unit/domain/test_workspace_config.py`, `tests/integration/test_json_repository.py`, `tests/integration/test_json_context_repository.py`, `tests/unit/infrastructure/test_json_section_repository.py`, `tests/unit/infrastructure/test_filesystem_asset_repository.py`, `tests/unit/application/test_imports.py`, `tests/unit/application/test_docx_import.py`.
- Create: `tests/fixtures/workspaces/legacy/` with sanitized representative workspaces for each evidenced historical format.
- Create: `docs/superpowers/specs/2026-09-21-workspace-format-inventory.md` as the migration decision record.

**Interfaces:**
- Consumes: all current persisted readers/writers and real fixtures available in repository; no chosen canonical schema yet.
- Produces: decision record naming each persisted representation, exact readers/writers/tests, version marker (or absence), and whether it is authored content, generated artifact, root configuration/registry, or operational state. `docs.config.json` and registry root paths are configuration/registry, not workspace document content. This record is the approval gate before schema implementation.

- [x] Trace `docs.config.json`, workspace registry files, `document.json`, template JSON, context JSON, section front matter, assets/import staging, manifests/provenance, and X20 artifacts to concrete readers/writers and exact tests. Separate root configuration and registry from workspace contents.
- [x] Enumerate historical source formats only when a current reader/writer, checked-in fixture, or supplied real workspace proves the format exists; list unsupported formats as rejected.
- [x] Add a fixture-driven characterization test per supported source format before changing runtime behavior.
- [x] Run: `uv run pytest tests/unit/application/test_workspaces.py tests/unit/domain/test_workspace.py tests/unit/domain/test_workspace_config.py tests/integration/test_json_repository.py tests/integration/test_json_context_repository.py tests/unit/infrastructure/test_json_section_repository.py tests/unit/infrastructure/test_filesystem_asset_repository.py tests/unit/application/test_imports.py tests/unit/application/test_docx_import.py -q` (observed: 97 passed).
- [x] Record maintainer decisions for supported source, one-root policy, strict marker, exclusions, artifact handling, separate-destination publication, cutover, and recovery.
- [x] Commit: `test: inventory workspace persistence formats` (`8bf7e02a`).

### Task 2: Specify and validate the canonical workspace schema

**Files:**
- Modify: `src/docs/application/workspaces.py`, `src/docs/infrastructure/persistence/json_repository.py`, `json_context_repository.py`, `json_section_repository.py`, and `filesystem_asset_repository.py` as assigned by the approved inventory.
- Test: `tests/unit/application/test_workspaces.py`, `tests/unit/domain/test_workspace.py`, `tests/unit/domain/test_workspace_config.py`, `tests/integration/test_json_repository.py`, `tests/integration/test_json_context_repository.py`, `tests/unit/infrastructure/test_json_section_repository.py`, `tests/unit/infrastructure/test_filesystem_asset_repository.py`.

**Interfaces:**
- Consumes: Task 1 inventory.
- Produces: the exact root marker `<workspace-root>/workspace.json` containing only `{"schema":"docs.workspace/v1"}`, a closed canonical validator, and one-root descendant enforcement for `documents/` and `templates/`.

- [ ] Write failing validator tests for the exact supported object plus missing file/field, non-object/non-string/malformed JSON, duplicate keys, unknown fields, and unsupported future versions.
- [ ] Write failing root tests proving `documents/` and `templates/` must resolve below the registered root and ordinary runtime rejects split roots before any write.
- [ ] Make normal workspace resolution reject missing/legacy/unsupported version with typed actionable error before any write.
- [ ] Verify existing authoring operations still read/write canonical workspace files.
- [ ] Run: `uv run pytest tests/unit/application/test_workspaces.py tests/unit/domain/test_workspace.py tests/unit/domain/test_workspace_config.py tests/integration/test_json_repository.py tests/integration/test_json_context_repository.py tests/unit/infrastructure/test_json_section_repository.py tests/unit/infrastructure/test_filesystem_asset_repository.py tests/unit/application/test_imports.py -q`.
- [ ] Commit: `feat: require canonical workspace format version`.

### Task 3: Implement migration inspection and report-only mode

**Files:**
- Create: `src/docs/application/workspace_migration.py` (migration use case; only legacy-format knowledge).
- Modify: `src/docs/cli/commands/workspace_app.py` to register a single explicit `docs workspace migrate` command.
- Create: `tests/unit/application/test_workspace_migration.py`, `tests/integration/test_workspace_migration.py`.

**Interfaces:**
- Consumes: canonical validator from Task 2 and versioned source adapters derived from Task 1.
- Produces: `docs workspace migrate (--source <root> | --legacy-config <docs.config.json>) --destination <destination> [--dry-run|--apply] [--json]`. Exactly one source selector is required: `--source` handles a rooted layout; `--legacy-config` explicitly locates split legacy document/template roots without copying or changing that config. Dry-run is the default and only explicit `--apply` may create the destination. The report names all selected source roots, detected format, preserved records, omitted rebuildable artifacts, excluded config/registry/X20 state, transformations, errors, scratch policy, and destination. It never changes workspace selection.

- [ ] Add tests for each supported historical format, already-canonical idempotence, malformed input, and unsupported/ambiguous classification.
- [ ] Implement read-only source detection and deterministic human-readable/JSON report before conversion.
- [ ] Assert dry-run leaves the source and destination parent unchanged.
- [ ] Test CLI requires exactly one source selector and a distinct destination, defaults to dry-run, and requires `--apply` for destination creation. Cover rooted and explicit split-root inputs. JSON and text reports carry the same selected roots, detected format, preservation/exclusion decisions, transformations, errors, publication policy, and recovery guidance.
- [ ] Run: `uv run pytest tests/unit/application/test_workspace_migration.py tests/integration/test_workspace_migration.py tests/unit/cli/test_workspace_migrate.py -q`.
- [ ] Commit: `feat: report workspace migration plans without mutation`.

### Task 4: Convert into scratch, validate, and publish to a separate destination

**Files:**
- Modify: `src/docs/application/workspace_migration.py`
- Modify: Create `src/docs/infrastructure/persistence/workspace_migration_filesystem.py` as the safe staging/path-check/atomic-directory-publication adapter; use `filesystem_asset_repository.py` only for its existing asset-copy role.
- Modify: `tests/integration/test_workspace_migration.py`.

**Interfaces:**
- Consumes: Task 3 report/format classifier and Task 2 canonical validator.
- Produces: explicit source-to-destination conversion. Write only to a scratch sibling of the destination until full validation, then atomically rename the scratch tree to the absent destination. Leave the source byte-for-byte untouched and do not alter registry/config selection. No force/replace flag is supported.

- [ ] Add failure-injection tests proving conversion/validation/publication errors leave source untouched and do not expose a partial destination.
- [ ] Add tests for symlink/path escape, source/destination overlap, destination-inside-source, source-inside-destination, changed source evidence, existing-destination refusal, and unsupported cross-filesystem/non-atomic publication.
- [ ] Add artifact-policy tests proving authored/evidence-bearing records are preserved, rebuildable delivery output is omitted and reported, config/global registry/X20 state is untouched, and unknown records fail closed.
- [ ] Add idempotence test for canonical source and byte/content preservation assertions for authored files/assets.
- [ ] Implement transactional staging and atomic destination publication. Clean scratch after pre-publication failure when safe; if cleanup fails, report its exact path. Document pre-cutover destination deletion/rerun and post-cutover source reselection recovery.
- [ ] Run: `uv run pytest tests/integration/test_workspace_migration.py tests/unit/cli/test_workspace_migrate.py tests/integration/test_json_repository.py tests/integration/test_json_context_repository.py tests/unit/infrastructure/test_json_section_repository.py tests/unit/infrastructure/test_filesystem_asset_repository.py -q`.
- [ ] Commit: `feat: migrate workspaces with validated atomic publication`.

### Task 5: Separate operational-store decision and enforce runtime boundary

**Files:**
- Modify: `src/docs/application/workspaces.py`, `src/docs/cli/commands/workspace_app.py`, `src/docs/cli/commands/doc_app.py`, `src/docs/cli/commands/context_app.py`, `src/docs/cli/commands/document_app.py`, and `src/docs/api/application.py` to reject noncanonical workspace content during ordinary operations.
- Test: `tests/unit/api/test_application.py`, `tests/unit/workers/test_composition.py`, `tests/unit/workers/test_runner.py`, `tests/unit/workers/test_service.py`, `tests/unit/application/test_workspaces.py`, `tests/architecture/test_boundaries.py`.

**Interfaces:**
- Consumes: canonical workspace validator and migration command.
- Produces: production readers accept only a registered single-root canonical workspace with the exact v1 marker. Split roots and unversioned roots receive migration guidance. This plan does not alter or migrate external config/global registry or operational X20 schemas/history; any later export needs a separate reviewed plan.

- [ ] Add tests proving unversioned and split-root workspaces are rejected by ordinary CLI/API/worker runtime with migration guidance, while the migration tool still accepts the evidenced legacy input.
- [ ] Confirm tests show `docs.config.json`, the global registry, and filesystem/SQLite run/queue/lease records remain outside the converter and unchanged by migration.
- [ ] Run: `uv run pytest tests/unit/api/test_application.py tests/unit/workers/test_composition.py tests/unit/workers/test_runner.py tests/unit/workers/test_service.py tests/unit/application/test_workspaces.py tests/architecture/test_boundaries.py -q`.
- [ ] Commit: `refactor: enforce canonical workspace runtime boundary`.

### Task 6: Document, audit references, and verify recovery contract

**Files:**
- Modify: `README.md`, `docs/architecture.md`, `docs/runtime-guide.md`, `AGENTS.md`.
- Test: migration, runtime boundary, and full workspace-related suites.

**Interfaces:**
- Consumes: completed migration CLI and canonical schema.
- Produces: one documented source-to-destination migration path, an explicit cutover step, recovery instructions based on the unchanged source, and explicit config/registry/X20/generated-artifact boundaries.

- [ ] Search for legacy schema readers outside migration package; move only necessary source readers to migration or delete dead readers after confirming no consumer.
- [ ] Document source/destination selection, dry-run output, absent-destination rule, artifact preservation/omission, explicit registry/config cutover, unsupported-format behavior, scratch cleanup, rollback by reselecting the unchanged source, and optional deletion of the old root only as a later manual operation.
- [ ] Run: `uv run pytest tests/unit/application/test_workspaces.py tests/unit/domain/test_workspace.py tests/unit/domain/test_workspace_config.py tests/integration/test_json_repository.py tests/integration/test_json_context_repository.py tests/unit/infrastructure/test_json_section_repository.py tests/unit/infrastructure/test_filesystem_asset_repository.py tests/unit/application/test_imports.py tests/unit/application/test_docx_import.py tests/unit/application/test_workspace_migration.py tests/integration/test_workspace_migration.py tests/unit/cli/test_workspace_migrate.py tests/architecture -q`.
- [ ] Run: `uv run ruff check src/docs tests` and `uv run mypy src/docs`.
- [ ] Commit: `docs: document canonical workspace migration and recovery`.
