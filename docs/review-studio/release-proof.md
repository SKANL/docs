# Review Studio release proof (S7.3)

Accessibility, keyboard, motion, stream-cleanup, origin and performance proofs. All commands run from the repository root; results are from the S7.3 run against the real sidecar fixture (`review-studio/e2e/api-fixture.mjs`, started with `DOCS_SIDECAR_CORS_ORIGINS=http://127.0.0.1:5173`).

## Budgets

| Budget | Limit | Observed |
|---|---|---|
| Entry chunk (referenced by `dist/index.html`), raw | <= 350 kB | 204.99 kB (was 713.67 kB before code splitting) |
| Entry chunk, gzip | <= 110 kB | 65.89 kB (was 210.08 kB) |
| Initial JS (entry + modulepreloaded `react` chunk), gzip | <= 150 kB (tripwire) | 135.32 kB (428.65 kB raw) |
| Home: navigation start to visible heading, dev server + real sidecar | < 3 s | 1087, 345, 536 ms and 1128, 393, 397 ms (two runs, 3 samples each; first sample includes cold module transform) |

The Home figure is measured on the Vite dev server, so it is a ceiling for a cold unbundled load, not a production number.

How the entry chunk was brought under budget: every feature area is a `React.lazy` route (skeleton `Suspense` fallback in `AppShell`), the command palette and the toaster load on first use, `sonner`'s `toast` is imported dynamically by `useAction`, and `react`/`react-dom`/`scheduler` are a separate long-cached `react` chunk (`vite.config.ts`). The initial-JS tripwire exists so moving bytes between chunks cannot hide growth.

## Reproduce each proof

| Proof | Command | Observed |
|---|---|---|
| Types | `npm --prefix review-studio run typecheck` | clean |
| Lint | `npm --prefix review-studio run lint` | 0 problems |
| Unit/component | `npm --prefix review-studio run test` | 21 files, 233 tests passed |
| Bundle budget | `npm --prefix review-studio run build && npm --prefix review-studio run check:budget` | see Budgets table |
| Whole E2E suite | `npm --prefix review-studio run test:e2e -- --reporter=line` | 49 passed, twice, each on a fresh fixture |
| Axe (WCAG 2.0 A/AA, 2.1 AA; serious and critical) | `npx playwright test e2e/accessibility.spec.ts` (in `review-studio/`) | 24 pages/states, 0 violations after fixes |
| Keyboard journeys and visible focus | `e2e/keyboard.spec.ts` | 4 passed |
| Reduced motion (dialog, toast) | `e2e/reduced-motion.spec.ts` | 2 passed; longest duration <= 1 ms, no running animation |
| Selected-run stream cleanup | `e2e/run-stream.spec.ts` | 2 progress requests for run A, both ended; none after leaving; A's frame never shown on run B |
| API origin restriction | `e2e/origin.spec.ts` | 3 passed |
| Performance | `e2e/performance.spec.ts` | see Budgets table |

Routes covered by axe: `/`, `/configure`, `/configure/{workspaces,templates,diagnostics,plugins}`, `/authoring/{sources,classification,assets,context,sections,revisions}`, `/pipeline`, a run detail, `/review/{findings,artifacts,evidence,baselines,diff,qa,graph}`, `/delivery`, `/tools`, and the open command palette.

## Accessibility violations found and fixed

First axe run: 15 of 24 pages failed.

- `color-contrast` on inactive tab triggers (`text-foreground/60` on the muted tab bar): now `text-muted-foreground` (`components/ui/tabs.tsx`).
- `color-contrast` on the "Needs attention" warning badge: light `--warning` token darkened from `oklch(0.55 0.13 80)` to `oklch(0.48 0.12 75)` (`globals.css`).
- `aria-valid-attr-value` (critical) on Review tabs: triggers pointed at a tab panel that did not exist. The active Review panel is now a real `TabsContent` (`QualityRoute.tsx`).
- `scrollable-region-focusable`: the shared `Table` scroll container is keyboard-focusable (`components/ui/table.tsx`).

Dark mode was not part of the axe sweep.

## Behaviours that were already correct (checks passed on first run)

Keyboard journeys, focus return after Esc on the palette and destructive dialogs, a failed destructive action keeping its dialog open with the server error, reduced motion, run-stream abort on navigation, and origin restriction all passed when first written. They are regression guards, not fixes.

## Notes and limits

- Origin restriction: the sidecar answers an unconfigured origin's preflight with a rejected status and no `access-control-allow-origin`; the browser blocks the read. This is verified through Playwright's request context and a real browser fetch from `http://evil.example`.
- The run-stream check mocks run records and the progress stream (frames are fulfilled once, then held open) because the fixture's real runs finish in seconds; it asserts on request lifecycle events, not on a mocked abort.
- `review-studio.spec.ts` "selects a workspace" is not idempotent on a reused fixture (it creates and renames a workspace, and state persists between runs; the likely cause of the failure is a leftover workspace from the previous run, not verified). Both counted full-suite runs used a fresh fixture. A run on a reused fixture failed on exactly that test, at the rename assertion.
