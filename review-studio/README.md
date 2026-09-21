# Review Studio

Standalone browser-first React + TypeScript + Vite foundation for reviewing document runs, evidence, artifacts, and publication readiness.

## Run
npm install
npm run dev

Also available: npm run build, npm run typecheck, npm test, and npm run lint. Lint runs ESLint over the production TypeScript source.

For local development, `.env.development` points to the local sidecar at
`http://127.0.0.1:8765/v1`; start the sidecar with an explicit workspace before
running the app. For a self-hosted or authenticated deployment, override
`VITE_DOCS_API_BASE_URL` with that API's `/v1` URL and provide
`VITE_DOCS_API_TOKEN` when a bearer token is required. Remote API failures are
shown in the UI and never replaced with demo data.

Tests inject fetch-backed API clients; production and development always use the configured remote API. No external assets or router dependency is required.

Run the browser fixture tests with `npm run test:e2e`; they start a local API fixture and exercise sessions, findings, graph data, skip-link navigation, and visible focus.
