# Review Studio

Standalone browser-first React + TypeScript + Vite foundation for reviewing document runs, evidence, artifacts, and publication readiness.

## Run
npm install
npm run dev

Also available: npm run build, npm run typecheck, npm test, and npm run lint. There is no lint configuration yet; the lint script is intentionally a documented no-op while the foundation is being established.

Set `VITE_DOCS_API_BASE_URL` to the authenticated `/v1` API before starting the app. Remote API failures are shown in the UI and never replaced with demo data.

The deterministic mock adapter in `src/api/mockApi.ts` is development/test-only and requires the explicit `VITE_REVIEW_STUDIO_MOCK_API=true` opt-in (or an injected test dependency). No external assets or router dependency is required.

Run the browser fixture tests with `npm run test:e2e`; they start a local API fixture and exercise sessions, findings, graph data, skip-link navigation, and visible focus.
