# Review Studio Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the shared web/Tauri Review Studio in vertical slices until it provides total approved CLI parity without duplicating Python business logic.

**Architecture:** React/Vite is a single client for browser and Tauri. Python application services remain authoritative; new HTTP routes are thin adapters registered by `X20Application` and described by OpenAPI. Feature modules invoke the typed `ReviewApi`, while Tauri remains a UI-agnostic local-runtime wrapper.

**Tech Stack:** Python, FastAPI-compatible X20 HTTP API, OpenAPI v2, React 18, TypeScript, Vite, shadcn/ui (Radix), Tailwind CSS, TanStack Query, React Router, AI Elements registry, Vitest, Playwright, Tauri 2.

**Spec:** `docs/superpowers/specs/2026-09-27-review-studio-redesign-design.md`

## Global Constraints

- Use one React/Vite frontend for web and desktop; never edit generated `desktop/src/`.
- UI invokes canonical HTTP/application-service contracts; never invoke the CLI or reproduce business rules in TypeScript.
- Use shadcn/ui Radix primitives and approved registry components only for user-facing controls.
- Keep `desktop/src-tauri/src/lib.rs` UI-agnostic; native behavior is exposed only through a small platform capability adapter.
- Every async operation exposes typed result/error/provenance and selected-run progress where supported.
- Every destructive action uses an accessible confirmation dialog; keyboard, mouse, and screen-reader paths are acceptance criteria.
- Each task ships tests with code and ends in one Conventional Commit. Preserve unrelated `.atl` changes.
- Use `npm --prefix review-studio run typecheck|lint|test|build|test:e2e`, `uv run pytest ...`, and desktop checks named by the relevant task.

## Review Focus

1. Desktop and browser API origins must remain restricted to intended loopback/configured origins; test Tauri CSP/CORS after route changes.
2. Changing workspace, document, route, or selected run must close obsolete SSE streams and prevent stale progress from overwriting the active view.
3. A capability shown by the UI must be backed by a real route and scope; unsupported commands must never render as fake actions.
4. Destructive workspace/document/template/release actions must restore focus and surface an actionable server error on failure.
5. The CLI→API→UI parity matrix must distinguish browser availability from intentional Tauri-only host integration, not silently omit a command.

## File Structure

| Area | Files created or changed | Responsibility |
| --- | --- | --- |
| Contract | `src/docs/api/openapi.py`, `src/docs/api/application.py`, `src/docs/api/server.py`, `src/docs/api/workspace_dto.py` | OpenAPI schemas/routes and thin canonical-service adapters. |
| CLI parity | `docs/review-studio/cli-api-ui-parity.md`, `tests/architecture/test_cli_api_ui_parity.py` | One authoritative command-to-route-to-UI ownership matrix. |
| App foundation | `review-studio/components.json`, `tailwind.config.ts`, `postcss.config.js`, `src/app/*`, `src/components/ui/*`, `src/components/shared/*` | Design system, providers, shell, router, shared presentation. |
| Frontend boundary | `review-studio/src/api/{models,client,factory,errors,transport}.ts`, `src/api/domains/*`, `src/lib/{capability,action}-registry.ts` | Typed API transport, capability discovery, action registry. |
| Feature modules | `review-studio/src/features/{workspace,documents,authoring,pipeline,quality,delivery,templates,tools}/**` | Domain routes and composition only. |
| Tests | `tests/unit/api/*`, `tests/integration/*`, `review-studio/src/test/**`, `review-studio/e2e/**` | Contract, component, real-sidecar, browser, and desktop proof. |

## Capability ownership matrix

| Slice | CLI command groups | New UI domains | API outcome |
| --- | --- | --- | --- |
| 0 | `guide`, `explain`, `doctor`, `stamp`; cross-cutting contracts | Shell, command palette, help, diagnostics | Capability catalogue and diagnostic adapters. |
| 1 | `workspace *`, `doc *` | Workspace and document control | Full workspace/document lifecycle routes. |
| 2 | `asset *`, `context *`, `source *`, `document ingest/classify`, `section *`, `stamp-section`, `doc revise` | Sources and authoring | Asset, context, section/revision adapters. |
| 3 | `document plan/prepare/run/build/verify`, `run *` | Pipeline and runs | Plan/run/watch and durable operation routes. |
| 4 | `document evidence/passport/baseline/inspect/diff` | Quality and review | Evidence, baseline-write, inspect/diff routes. |
| 5 | `document package/publish/release` | Delivery | Package/release operation routes. |
| 6 | `template *`, `collect-*`, `build/review-rules`, `build-ledger`, `docx *`, `translate`, plugins | Configure and tools | Template-write and specialist-tool adapters. |
| 7 | Every row above | Parity closure | Automated completeness proof and legacy removal. |

---

## Slice 0 — Foundation and parity contract

### Task S0.1: Create the canonical capability catalogue

**Files:** Create `docs/review-studio/cli-api-ui-parity.md`, `tests/architecture/test_cli_api_ui_parity.py`; Modify `src/docs/api/openapi.py`, `src/docs/api/application.py`, `review-studio/src/api/models.ts`.

**Interfaces:** `GET /v2/capabilities -> CapabilityCatalog`; `CapabilityCatalog.groups: CapabilityGroup[]`; each capability has `id`, `cli_command`, `route`, `scopes`, `surface`, `slice`, and `status`.

- [ ] Write architecture and API tests that fail when a CLI command has no matrix row or when an advertised capability has no registered route.
- [ ] Run `uv run pytest tests/architecture/test_cli_api_ui_parity.py tests/unit/api/test_openapi.py -q`; expect failure because the catalogue is absent.
- [ ] Implement the catalogue from command metadata and register `GET /v2/capabilities` through `X20Application`; document every current command group in the matrix.
- [ ] Re-run the focused tests; expect PASS. Commit: `feat(api): expose review studio capabilities`.

### Task S0.2: Establish shadcn application infrastructure

**Files:** Create `review-studio/components.json`, `tailwind.config.ts`, `postcss.config.js`, `src/app/styles/globals.css`, `src/lib/cn.ts`, `src/components/ui/**`; Modify `review-studio/package.json`, `src/main.tsx`.

**Interfaces:** `cn(...inputs: ClassValue[]): string`; CSS semantic tokens for background, foreground, card, muted, destructive, focus ring, and status colors.

- [ ] Add failing render tests proving the root loads tokenized styles and a Radix dialog can receive initial focus.
- [ ] Run `npm --prefix review-studio test -- --runInBand`; expect missing configuration/components.
- [ ] Initialize shadcn non-interactively with the Radix base; add only primitives required by Slice 0 (`button`, `dialog`, `command`, `tooltip`, `sheet`, `toast`, `skeleton`, `dropdown-menu`).
- [ ] Run `npm --prefix review-studio run typecheck`, `lint`, `test`, and `build`; expect PASS. Commit: `feat(ui): add review studio design foundation`.

### Task S0.3: Replace the monolith with router, providers, and shell

**Files:** Create `src/app/{App,providers,router,routes}.tsx`, `src/app/shell/{AppShell,Sidebar,Topbar,CommandPalette,ActivityCenter}.tsx`, `src/components/shared/{AsyncBoundary,ErrorState,EmptyState,PageHeader,ConfirmActionDialog}.tsx`; Replace `src/App.tsx`, `src/styles.css`; Modify `src/test/app.test.tsx`.

**Interfaces:** `AppProviders({ api, children })`; `AppShell({ children })`; `ActionDefinition { id; label; shortcut?; isAvailable(context); execute(context) }`.

- [ ] Write failing tests for route focus management, skip-link target, command-palette keyboard open/close, and dialog focus restoration.
- [ ] Run `npm --prefix review-studio test -- --run src/test/app.test.tsx`; expect failures against the legacy hash screen.
- [ ] Implement React Router routes, providers, responsive shell, live-region activity center, and command palette backed by the action registry; remove the non-functional legacy command button.
- [ ] Run frontend unit checks and `npm --prefix review-studio run test:e2e`; expect PASS. Commit: `feat(ui): add shared application shell`.

### Task S0.4: Split transport and add capability-aware actions

**Files:** Create `src/api/{errors,transport}.ts`, `src/api/domains/{workspaces,documents,pipeline,artifacts,review,delivery,administration}.ts`, `src/lib/{capability-registry,action-registry}.ts`; Modify `src/api/{models,client,factory}.ts`, `src/test/{client,apiFactory}.test.ts`.

**Interfaces:** `ReviewApi.getCapabilities(): Promise<CapabilityCatalog>`; `ApiError { code; message; details?; retryable }`; `createActionRegistry(catalog, api): ActionDefinition[]`.

- [ ] Write failing client tests for malformed capability data, missing scopes, normalized API errors, and unavailable actions.
- [ ] Run `npm --prefix review-studio test -- --run src/test/client.test.ts`; expect failure for the new interface.
- [ ] Move transport normalization out of feature concerns; make action availability depend solely on the capability catalogue and current selection.
- [ ] Run typecheck/lint/unit/build checks; expect PASS. Commit: `refactor(ui): isolate typed operation transport`.

## Slice 1 — Workspace and document control

### Task S1.1: Complete workspace lifecycle adapters

**Files:** Modify `src/docs/api/{openapi,application,server,workspace_dto}.py`, `tests/unit/api/{test_openapi,test_api,test_http}.py`, `review-studio/src/api/{models,domains/workspaces}.ts`.

**Interfaces:** `POST /v2/workspaces/{id}/use`; `GET /v2/workspaces/{id}/status`; `POST /v2/workspaces/{id}/migrate`; all delegate to workspace application services.

- [ ] Add failing API tests for select, status, migration success, missing workspace, and unauthorized scope.
- [ ] Run focused Python tests; expect route absence.
- [ ] Register DTOs/routes/adapters without calling CLI code; update OpenAPI and frontend types.
- [ ] Re-run focused tests and `uv run pytest tests/architecture -q`; expect PASS. Commit: `feat(api): add workspace lifecycle operations`.

### Task S1.2: Complete document lifecycle adapters

**Files:** Modify `src/docs/api/{openapi,application,server}.py`, `tests/unit/api/test_*.py`, `review-studio/src/api/{models,domains/documents}.ts`.

**Interfaces:** document `init`, `current`, `use`, `show`, `rename`, and `delete` routes return canonical document DTOs and provenance.

- [ ] Write failing contract tests for each CLI-equivalent document transition and active-document persistence.
- [ ] Run focused Python tests; expect missing routes.
- [ ] Add thin application-service adapters and OpenAPI definitions; do not calculate active state in React.
- [ ] Re-run focused tests; expect PASS. Commit: `feat(api): complete document lifecycle routes`.

### Task S1.3: Build workspace/document user journeys

**Files:** Create `src/features/workspace/**`, `src/features/documents/**`; Modify `src/app/routes.tsx`, frontend factories/tests, `review-studio/e2e/review-studio.spec.ts`.

**Interfaces:** `WorkspaceSwitcher`; `WorkspaceFormDialog`; `DocumentCreateDialog`; `DocumentStatusPanel`; feature hooks consume `ReviewApi` only.

- [ ] Write failing component/E2E tests for create/select/migrate/rename/delete with cancel and server-error recovery.
- [ ] Run the focused tests; expect legacy view incompatibility.
- [ ] Implement guided dialogs/pages with one primary next action, capability gating, and desktop-safe local bootstrap messaging.
- [ ] Run frontend checks plus `uv run pytest tests/integration/test_workspace_migration.py -q`; expect PASS. Commit: `feat(ui): add workspace and document control`.

## Slice 2 — Sources and authoring

### Task S2.1: Add source, asset, and context adapters

**Files:** Modify `src/docs/api/{openapi,application,server}.py`, relevant services under `src/docs/application/`, `tests/unit/api/test_*.py`; Create `review-studio/src/api/domains/authoring.ts`.

**Interfaces:** asset CRUD, source ingest, context elicit/ingest/show/remove operations return typed result/provenance DTOs.

- [ ] Write failing API tests for valid input, corrupt source degradation, pending classification, and context removal.
- [ ] Run focused Python tests; expect absent adapters.
- [ ] Delegate HTTP handlers to existing `asset_app`, `source_app`, and `context_app` services; register OpenAPI schemas.
- [ ] Re-run focused tests; expect PASS. Commit: `feat(api): expose source and context workflows`.

### Task S2.2: Add section, review, stamp, and revision adapters

**Files:** Modify API files/tests; extend `review-studio/src/api/{models,domains/authoring}.ts`.

**Interfaces:** explicit operations for build/pack/review section/document, `stamp-section`, and `doc revise`; long actions return run/result references rather than UI-inferred status.

- [ ] Write failing contract tests for authored-content preservation, review findings, stamp provenance, and revision diff creation.
- [ ] Run focused tests; expect missing route support.
- [ ] Add canonical adapters over section/document services and typed frontend models.
- [ ] Re-run focused tests; expect PASS. Commit: `feat(api): expose section authoring operations`.

### Task S2.3: Deliver the authoring workspace

**Files:** Create `src/features/authoring/{routes,sources,classification,context,assets,sections,revisions}/**`; retire `src/components/SectionEditor.tsx` after feature replacement; extend component/E2E tests.

**Interfaces:** `AuthoringRoute`; `SourceIntakePanel`; `ContextForm`; `SectionEditor`; `RevisionTimeline`; `ReviewFindingsPanel`.

- [ ] Write failing tests for progressive prerequisites, accessible editors, classification confirmation, review-to-fix navigation, and failed source ingestion.
- [ ] Run focused frontend tests; expect unavailable routes/components.
- [ ] Implement the guided authoring flow using shared dialogs, forms, tables, and action registry entries.
- [ ] Run frontend E2E plus relevant `uv run pytest tests/integration/test_document_runtime_vertical_journey.py -q`; expect PASS. Commit: `feat(ui): add guided document authoring`.

## Slice 3 — Pipeline and runs

### Task S3.1: Add plan, run, and watch contracts

**Files:** Modify `src/docs/api/{openapi,application,server}.py`, run/pipeline tests, `review-studio/src/api/domains/pipeline.ts`.

**Interfaces:** `POST /v2/documents/{id}/plan`; pipeline action accepts a declared operation; run list supports filters/page cursor; watch stream binds a selected run and terminal state.

- [ ] Write failing tests for plan, pagination, selected-run SSE, cancellation, retry, and stream cleanup authorization.
- [ ] Run focused API tests; expect missing contracts.
- [ ] Extend `_document_action()` and run adapters without duplicating pipeline orchestration.
- [ ] Re-run focused tests; expect PASS. Commit: `feat(api): add durable pipeline run contracts`.

### Task S3.2: Deliver pipeline launcher and run center

**Files:** Create `src/features/pipeline/**`; modify app routes, shared `RunProgress`, client tests, and E2E fixture/spec.

**Interfaces:** `PipelineLauncher`; `RunDetailPage`; `RunWatchPanel`; `useRunStream(runId)` always aborts the prior stream on dependency change.

- [ ] Write failing tests for launch prerequisites, selected-run progress, navigation cleanup, retry/cancel, and terminal receipts.
- [ ] Run focused frontend tests; expect failure.
- [ ] Implement pipeline pages and SSE hook using the typed API contract and activity center.
- [ ] Run frontend checks and real-sidecar E2E; expect PASS. Commit: `feat(ui): add pipeline execution workspace`.

## Slice 4 — Review and visual quality

### Task S4.1: Add evidence, baseline-write, inspect, and diff adapters

**Files:** Modify API/OpenAPI/server/tests; extend `review-studio/src/api/domains/review.ts` and models.

**Interfaces:** evidence route, baseline promotion route, inspect route, and diff route return immutable evidence references. Update the existing test that intentionally forbids baseline POST.

- [ ] Write failing tests for baseline promotion, immutable evidence identity, unavailable previews, inspect, and diff.
- [ ] Run `uv run pytest tests/unit/api/test_openapi.py tests/unit/api/test_api.py -q`; expect baseline-route mismatch.
- [ ] Add thin adapters and replace the obsolete read-only baseline assertion deliberately.
- [ ] Re-run focused tests; expect PASS. Commit: `feat(api): add visual quality operations`.

### Task S4.2: Deliver review workspace

**Files:** Create `src/features/quality/{routes,findings,artifacts,previews,baselines,passports,graph,inspection,diff}/**`; modify shared preview/table components and E2E tests.

**Interfaces:** `FindingDetail`; `ArtifactPreview`; `BaselinePromotionDialog`; `InspectionPanel`; `DiffViewer`.

- [ ] Write failing tests for finding-to-evidence navigation, preview degradation, baseline confirmation, and empty graph states.
- [ ] Run focused frontend tests; expect failure.
- [ ] Implement structured evidence views, never raw JSON dumps; use AI Elements only where it improves structured inspection.
- [ ] Run frontend E2E and render-verification tests; expect PASS. Commit: `feat(ui): add quality review workspace`.

## Slice 5 — Delivery and release

### Task S5.1: Add package and release operation routes

**Files:** Modify API/OpenAPI/server/tests; extend `review-studio/src/api/domains/delivery.ts`.

**Interfaces:** package/release requests become auditable operations with destination, policy, result artifact, and run/reference identifiers.

- [ ] Write failing API tests for permitted destination, policy denial, failed publication, and immutable release evidence.
- [ ] Run focused tests; expect missing routes.
- [ ] Adapt existing package/publish/release services through `X20Application` and OpenAPI.
- [ ] Re-run focused tests; expect PASS. Commit: `feat(api): expose delivery operations`.

### Task S5.2: Deliver release workspace

**Files:** Create `src/features/delivery/{routes,package,publish,release,publications}/**`; update app routes and E2E tests.

**Interfaces:** `PackageDialog`; `PublishDialog`; `ReleasePanel`; `PublicationHistory`.

- [ ] Write failing tests for policy messaging, destination confirmation, failed delivery recovery, and receipt links.
- [ ] Run focused frontend tests; expect failure.
- [ ] Implement delivery flows that display server policy/results and never claim approval locally.
- [ ] Run frontend E2E and package-related Python integration tests; expect PASS. Commit: `feat(ui): add delivery workspace`.

## Slice 6 — Configuration and specialist tools

### Task S6.1: Add template and plugin management contracts

**Files:** Modify API/OpenAPI/server/tests; create `review-studio/src/api/domains/templates.ts`; extend administration domain.

**Interfaces:** template create/use/show/validate operations and plugin actions use strict DTOs; plugin read-only restrictions remain explicit when applicable.

- [ ] Write failing tests for template validation, force-overwrite refusal, missing template, and restricted plugin operations.
- [ ] Run focused tests; expect absent write paths.
- [ ] Add adapters over template/plugin services and OpenAPI schemas.
- [ ] Re-run focused tests; expect PASS. Commit: `feat(api): expose template administration`.

### Task S6.2: Add specialist-tool operation contracts

**Files:** Modify API/OpenAPI/server/tests; create `review-studio/src/api/domains/tools.ts`.

**Interfaces:** typed actions for collection, rules, ledger, DOCX inspection, translation, and doctor; long operations use standard run/provenance output.

- [ ] Write failing tests for doctor degradation, invalid translation input, DOCX inspection failure, and rules/ledger results.
- [ ] Run focused tests; expect missing adapters.
- [ ] Register thin handlers over `collection_app`, `docx_app`, `translate_app`, and `core_app` services.
- [ ] Re-run focused tests; expect PASS. Commit: `feat(api): expose specialist document tools`.

### Task S6.3: Deliver configuration and tools workspaces

**Files:** Create `src/features/{templates,tools}/**`; modify app routes/shared components/frontend E2E tests.

**Interfaces:** `TemplateEditorPage`; `TemplateValidationPanel`; `DoctorPanel`; `TranslationWorkflow`; `DocxInspectionPanel`.

- [ ] Write failing tests for advanced-action progressive disclosure, validation messages, download/provenance links, and unavailable optional tools.
- [ ] Run focused frontend tests; expect failure.
- [ ] Implement task-specific layouts and command actions; do not place specialist controls in the primary authoring flow.
- [ ] Run frontend checks and relevant Python integration tests; expect PASS. Commit: `feat(ui): add configuration and specialist tools`.

## Slice 7 — Parity closure and legacy retirement

### Task S7.1: Make parity coverage executable

**Files:** Modify `docs/review-studio/cli-api-ui-parity.md`, `tests/architecture/test_cli_api_ui_parity.py`; create `review-studio/e2e/parity.spec.ts` and fixture helpers.

**Interfaces:** each matrix row links one CLI command, one API operation, one UI route/action, owning slice, and automated proof.

- [ ] Write failing architecture tests for incomplete rows, missing proof references, and CLI/API/UI mismatch.
- [ ] Run parity tests; expect failures for unverified rows.
- [ ] Complete matrix evidence and parameterized API/UI smoke coverage for every supported command.
- [ ] Run all parity tests; expect PASS. Commit: `test: enforce cli api ui parity`.

### Task S7.2: Remove legacy frontend and verify cross-surface behavior

**Files:** Delete replaced legacy components/styles/tests only after equivalent feature coverage; modify `review-studio/src/App.tsx`, desktop packaging contracts, and E2E suite.

**Interfaces:** no public interface changes; imported app entry resolves exclusively to the new router/shell.

- [ ] Write failing regression tests proving no legacy hash routes, custom action wall, `window.prompt`, `window.confirm`, or raw JSON action output remain.
- [ ] Run frontend/desktop checks; expect legacy detections.
- [ ] Delete obsolete code and update packaging/real-sidecar tests to the new routes.
- [ ] Run `npm --prefix review-studio run typecheck`, `lint`, `test`, `build`, `test:e2e`, `npm --prefix desktop run test:sidecar`, and `uv run pytest tests/integration/test_desktop_packaging_contract.py -q`; expect PASS. Commit: `refactor(ui): retire legacy review studio`.

### Task S7.3: Final accessibility, performance, and release proof

**Files:** Create or modify accessibility/performance E2E assertions, `docs/review-studio/cli-api-ui-parity.md`, and release documentation.

**Interfaces:** documented performance budgets; testable keyboard path for every route/action; final desktop/browser proof receipts.

- [ ] Add failing E2E checks for keyboard-only critical journeys, dialog focus restoration, reduced motion, selected-run stream cleanup, and configured API origin restrictions.
- [ ] Run the checks; expect failures before final remediation.
- [ ] Fix only identified parity/a11y/performance gaps and attach evidence to the matrix.
- [ ] Run the full Python, frontend, E2E, and desktop verification suite; expect PASS. Commit: `test: verify review studio parity release`.

## Dependency order

`S0.1 → S0.4` precedes every UI task. Backend tasks in a slice precede their UI task. Slices execute in numeric order; S7 starts only after every prior matrix row is marked API-backed and UI-tested. A task may not start if it needs an unavailable API operation.

## Self-review

- **Spec coverage:** S0–S7 each have owned API, UI, verification, and retirement work. CLI groups, desktop parity, shadcn-only UI, canonical business logic, research constraints, and total parity are mapped.
- **Step scan:** every task has a failing-test, fail-run, implementation, pass-run, and Conventional Commit sequence.
- **Type consistency:** all frontend feature tasks depend on `ReviewApi`, `CapabilityCatalog`, `ActionDefinition`, and typed operation results; all backend work enters through `X20Application` and OpenAPI.
- **Review focus:** all five global failure classes appear in task test requirements, especially S0.1, S0.3, S1.3, S3.2, and S7.3.
- **Proportion:** this plan records interfaces, boundaries, files, and tests rather than source implementations.

## Execution Handoff

No implementation is authorized by this plan alone. Review it before implementation. The recommended execution method is **Subagent-driven** because the 22 work units span Python contracts, React, browser E2E, and Tauri packaging; each needs an independent focused review.
