# Review Studio: shared web and desktop redesign

Review Studio will become the complete graphical control plane for the document harness: one React/Vite application delivered both in a browser and inside the existing Tauri shell. The redesign ships in vertical slices, but the programme is not complete until every supported CLI capability has an equivalent, usable UI workflow or an explicitly documented non-interactive exclusion approved by maintainers.

## Quick path

1. Build Slice 0 before replacing product screens: establish the shared shell, canonical operation contracts, and the CLI-to-UI parity matrix.
2. Deliver each later slice as a complete user journey with API contract coverage, accessibility proof, and web/Tauri tests.
3. Close only after the parity matrix proves that the desktop and web clients can perform every supported CLI workflow without reimplementing business logic.

## Product decision

| Topic | Decision |
| --- | --- |
| Delivery surfaces | One React/Vite frontend for browser and Tauri desktop. |
| Desktop role | Tauri owns native integration, app-data bootstrap, sidecar supervision, and updater behavior; it does not own a second UI. |
| UI building blocks | shadcn/ui with the Radix base, plus approved registry components such as AI Elements. |
| Business logic | Python application services and the API remain canonical. The frontend invokes operation contracts; it never reproduces CLI business rules. |
| Delivery | Vertical slices from foundation to total CLI parity. No production UI implementation starts before the slice/task backlog is approved. |
| Excluded architecture | No Node `micro` service and no microfrontends. Neither solves a demonstrated boundary and both would create a second composition/deployment model. |
| AI interactions | AI Elements are available as UI primitives. Conversational or JSON-rendered AI workflows are optional enhancements, not a prerequisite for the core product. |

## Evidence

The current frontend is a monolithic hash-routed React screen with custom HTML/CSS and only partial API coverage (`review-studio/src/App.tsx`, `review-studio/src/styles.css`, `review-studio/src/api/*`). It does not expose many CLI flows, including portions of document lifecycle, workspace/document management, template and context operations, assets/source tools, rules/ledger, DOCX tooling, translation, and durable run control. The desktop package builds the same frontend and copies its distribution into the Tauri bundle (`desktop/scripts/sync-review-studio.ps1`, `desktop/src-tauri/tauri.conf.json`).

Interaction research informs the design without copying another product: Linear demonstrates searchable contextual commands and keyboard/mouse parity; Obsidian demonstrates task-specific workspace layouts. See [Linear contextual command menu](https://linear.app/changelog/2019-10-07-contextual-command-menu), [Linear desktop app](https://linear.app/changelog/2022-03-15-new-desktop-app), and [Obsidian workspaces](https://obsidian.md/help/plugins/workspaces).

## Architecture

### Canonical operation boundary

Every user action is represented once as an API operation contract, with typed input, result, status, error, provenance, and—where applicable—run/progress identifiers. The CLI and UI must call the same application-service semantics. If a CLI capability lacks an API operation, the responsible slice adds a thin API adapter over the existing application service; it must not embed the rule in React.

The frontend owns presentation state only: navigation, selection, in-progress interaction state, form drafts, accessibility focus, and cached server representations. It does not calculate document validity, reproduce pipeline orchestration, or infer release eligibility.

### Information architecture

The application shell has a persistent workspace/document switcher, global command palette, notifications, and context-aware help. Main task areas are:

- **Home:** current document readiness, blockers, recent runs, and next safe action.
- **Authoring:** sources, classification, assets, context, sections, and revisions.
- **Pipeline:** planning, preparation, builds, verification, run history, and watch.
- **Review:** findings, artifacts, previews, visual baselines, passports, inspect, and diff.
- **Delivery:** package, publish, releases, and evidence.
- **Configure:** workspaces, documents, templates, plugins, rules, and diagnostics.

A task page shows one primary action and its prerequisites. The command palette and contextual menus expose the same actions, including shortcuts, without creating a competing action model.

### Cross-surface behavior

The browser connects to the configured remote or local API. Tauri starts and supervises the loopback sidecar, initializes its desktop workspace, and provides native-only affordances such as updater integration. Both surfaces use the same routes, feature modules, operation clients, and accessibility semantics.

## Slice catalogue

### Slice 0 — Product foundation and parity contract

**Outcome:** a usable shared application foundation exists before legacy product screens are replaced.

**Scope:** establish shadcn/Radix/Tailwind configuration; semantic tokens; a responsive dark-first app shell; routing; feature-module boundaries; a typed API/operation client; server-state caching and invalidation rules; command-palette infrastructure; notification/error conventions; and the authoritative CLI → API → UI parity matrix.

**Acceptance:** web and Tauri load the same shell; keyboard navigation, focus restoration, reduced-motion behavior, and accessible dialogs are tested; every CLI command group is classified as supported, missing API, planned slice, or approved exclusion; no legacy global action wall is reused as the new architecture.

### Slice 1 — Workspace and document control

**Outcome:** a user can establish and select the correct operating context without a terminal.

**Scope:** create, open, select, rename, migrate, and delete workspaces/documents; initialize document workspaces; display readiness and recovery states; persist selection; and make Tauri desktop bootstrap transparent.

**Acceptance:** all CLI workspace and document context-management workflows have guided UI equivalents, destructive actions use accessible confirmation, and web/Tauri behavior is identical except for declared native bootstrap affordances.

### Slice 2 — Sources and authoring

**Outcome:** an author can turn source material into an authored, traceable document in one guided flow.

**Scope:** import/ingest sources, classify sources, manage assets, complete context, create/edit/review/stamp sections, inspect revisions, and expose templates and rules required by authoring.

**Acceptance:** the UI displays dependencies and next actions rather than raw JSON; every source/context/section/revision action uses canonical API contracts and shows durable outcomes.

### Slice 3 — Pipeline execution

**Outcome:** users can plan, prepare, build, verify, observe, retry, cancel, and watch document operations without the CLI.

**Scope:** lifecycle planning/preparation, multi-format build, verification, durable run history, SSE progress, selected-run details, cancellation/retry, and watch controls.

**Acceptance:** run state survives navigation; errors are actionable and link to evidence; command palette and task pages invoke identical operations; progress and cancellation work on both delivery surfaces.

### Slice 4 — Review and visual quality

**Outcome:** reviewers can inspect evidence and make quality decisions in the product rather than interpreting raw artifacts manually.

**Scope:** findings, artifacts, previews, passports, graph, visual baselines, inspect, diff, and evidence views.

**Acceptance:** a reviewer can navigate from a failing run to the exact finding, preview, input evidence, and next operation; baseline creation and comparison are available where CLI supports them.

### Slice 5 — Delivery and release

**Outcome:** verified output can be packaged and published with visible provenance.

**Scope:** package, publish, release, destination selection, policy/result presentation, release history, and evidence links.

**Acceptance:** UI delivery behavior exactly reflects backend policy; it does not imply approval, mutate artifacts locally, or claim success without a server result.

### Slice 6 — Configuration and advanced tools

**Outcome:** all remaining administrative and specialist CLI workflows have an intentional home.

**Scope:** template create/use/show/validate, plugins, rules, ledger, collection, DOCX inspection, PDF translation, diagnostics, and remaining utility commands.

**Acceptance:** no command group remains unclassified in the parity matrix; complex specialist workflows receive progressive disclosure, documentation, and safe validation rather than being hidden behind raw JSON.

### Slice 7 — Parity closure and legacy retirement

**Outcome:** the new product reaches total approved parity and the legacy frontend is removed.

**Scope:** execute the parity matrix end-to-end, cross-surface regression suite, accessibility audit, performance budget verification, migration of saved user state where applicable, and deletion of replaced legacy components/styles/tests.

**Acceptance:** every matrix row has a passing UI/API/E2E evidence link; the old monolithic screen and bespoke design system are gone; all remaining differences are deliberate native integrations documented in the matrix.

## Programme-wide rules

- A slice may add UI only after its required API contract exists and is tested.
- A slice may not duplicate an application-service rule in TypeScript.
- UI components come from shadcn/ui or an approved registry. Product-specific composition remains in feature modules; primitives are not forked casually.
- Every destructive action uses an accessible confirmation flow; every async action has progress, cancellation semantics when supported, and recovery guidance.
- Keyboard, mouse, and screen-reader paths are first-class acceptance criteria.
- Web and Tauri must share feature code. Native-only behavior is isolated behind a capability adapter.
- The parity matrix is a release gate, not a documentation afterthought.

## Out of scope

- Replacing the Python domain/application architecture solely for visual reasons.
- Introducing a Node service, a second frontend, microfrontends, or an AI chat surface without a separately approved product need.
- Copying the visual identity of Linear, Obsidian, or any other researched product.

## Verification plan

Each slice must add contract tests for new API operations, React component/integration tests for user behavior, Playwright E2E coverage for the primary journey, and Tauri packaging/runtime checks where the surface differs. Slice 7 additionally requires a complete parity-matrix audit and accessibility/performance evidence.

## Next step

Review this design before the implementation backlog is written. Once approved, the backlog will decompose every slice into atomic tasks with ownership boundaries, dependencies, acceptance criteria, and exact verification commands.
