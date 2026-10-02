# Review Studio Redesign — ODD task record

## Objective
Deliver the approved shared web/Tauri frontend redesign in vertical slices, reaching full documented CLI parity without duplicating canonical application/business logic.

## Problem and rationale
The existing web and desktop frontends do not expose the full CLI capability set and have weak interaction flows. The approved design and implementation plan define the target architecture and slice boundaries.

## Scope and constraints
- Implement all slices S0–S7 in `docs/superpowers/plans/2026-09-27-review-studio-redesign.md` and its design spec.
- One React/Vite frontend serves browser and Tauri; Python application services remain authoritative; HTTP handlers are thin adapters.
- Use shadcn/Radix and approved registry components for controls; do not duplicate business rules in TypeScript.
- Preserve unrelated `.atl` changes in the primary checkout; work only in the managed worktree.
- Each task includes tests and ends with a Conventional Commit; never add AI co-author attribution.
- TDD mode: enabled by the approved plan's required failing-test-first sequence. Test runners: `uv run pytest ...`; `npm --prefix review-studio run typecheck|lint|test|build|test:e2e` as applicable.
- Delivery strategy: `ask-on-risk`; no PR or push authorized.
- Route: delegated direct for multi-file implementation; delegation is required by the repository's 4-file mapping and multi-file writer rules.

## Acceptance criteria
- All CLI command groups have explicit API/UI ownership and supported-surface status in the parity matrix.
- Every surfaced action maps to a real, capability-gated route and canonical service; no duplicate business logic.
- Web and desktop user journeys cover the approved capabilities with accessible interaction and error states.
- Applicable Python, frontend, integration, E2E, accessibility, and release checks pass or are recorded with explicit limitations.

## Progress checklist
- [x] S0.1 Capability catalogue — `cd9786da`.
- [x] S0.2 shadcn design foundation — `a528b993` (initial foundation; complete primitive/test proof remains part of S7 verification if not already satisfied).
- [x] S0.3 Shared application shell — `8a9159e0`.
- [x] S0.4 Typed transport and capability-aware actions — `b4513c14`.
- [x] S1.1 Workspace lifecycle API — `023ffd60`; focused API tests passed (150 tests).
- [x] S1.2 Document lifecycle API adapters — `feat(api): complete document lifecycle routes`; RED observed on missing service/routes, then focused API/OpenAPI/sidecar suite passed (176 tests) and Ruff passed.
- [ ] S1.3 Workspace/document journeys.
- [ ] S2.1 Sources, assets, and context API.
- [ ] S2.2 Sections, review, stamp, and revision API.
- [ ] S2.3 Authoring workspace.
- [ ] S3.1 Plan, run, and watch API.
- [ ] S3.2 Pipeline UI.
- [ ] S4.1 Evidence, baseline, inspect, and diff API.
- [ ] S4.2 Review workspace.
- [ ] S5.1 Package and release API.
- [ ] S5.2 Delivery UI.
- [ ] S6.1 Template and plugin API.
- [ ] S6.2 Specialist tools API.
- [ ] S6.3 Tools UI.
- [ ] S7.1 Executable parity coverage.
- [ ] S7.2 Retire legacy UI and cross-surface verification.
- [ ] S7.3 Accessibility, performance, and release proof.

## Decisions and evidence
- Reuse canonical application services from the API; do not invoke CLI commands from the UI or recreate their mechanics in frontend code.
- Do not generate/edit `desktop/src/`; it is generated from the shared frontend.
- S1.2 will adapt `DocumentService` through API composition, not introduce a second document lifecycle implementation.
- S1.2 memoizes the canonical `DocumentService` by resolved workspace root for one API application lifetime; the sidecar factory composes the service lazily, and the API does not repeat the full composition for each request.
- S1.2 execution route: delegated-direct was attempted first; after workers stopped without a complete implementation, the user explicitly directed the parent to continue as the single writer. Scope remained confined to the API slice.
- S1.2 implementation evidence: `uv run pytest tests/unit/api/test_application.py tests/unit/api/test_openapi.py tests/unit/test_sidecar.py -q` — 176 passed; `uv run ruff check src/docs/api/application.py src/docs/api/openapi.py src/docs/api/document_dto.py src/docs/sidecar.py tests/unit/api/test_application.py tests/unit/api/test_openapi.py tests/unit/test_sidecar.py` — passed. Runtime harness: N/A; this is an API adapter slice and its HTTP/service boundary is exercised by the focused API and sidecar tests.

## Next step
Continue with S1.3 workspace/document user journeys; S1.2 now exposes create/list/current/use/rename/delete through canonical DocumentService adapters and strict DTO/OpenAPI contracts.

## Relevant files
- `docs/superpowers/specs/2026-09-27-review-studio-redesign-design.md` — approved design.
- `docs/superpowers/plans/2026-09-27-review-studio-redesign.md` — implementation slices and checks.
- `docs/review-studio/cli-api-ui-parity.md` — parity ownership matrix.
- `src/docs/application/documents.py` — canonical document lifecycle service.
- `src/docs/api/application.py`, `src/docs/api/document_dto.py`, `src/docs/api/openapi.py` — lifecycle adapters, DTOs, and OpenAPI schemas.
- `src/docs/sidecar.py` — per-workspace canonical DocumentService composition.
- `tests/unit/api/test_application.py`, `tests/unit/api/test_openapi.py`, `tests/unit/test_sidecar.py` — lifecycle and composition coverage.
