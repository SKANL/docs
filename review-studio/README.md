# Review Studio

Standalone browser-first React + TypeScript + Vite foundation for reviewing document runs, evidence, artifacts, and publication readiness.

## Working modes, Advanced and language

The app opens in Spanish. On first run, Home asks how you want to work; the choice can be changed any time from the top bar.

- **Supervisar** (supervise): an agent writes the sections from the command line. You upload sources, review findings and deliver. Navigation shows Inicio, Generar, Revisar and Entregar.
- **Redactar** (write): you write and edit sections in the app. It adds the Redactar area (sources, classification, assets, context, sections, revisions) to the same four.
- **Avanzado** (Advanced switch, top bar): independent of the mode. It adds the technical areas, Configuración técnica and Herramientas, plus technical controls such as the release run on Entregar. Hidden areas keep their URLs; they are only unlisted.
- **Idioma** (language button, top bar): switches between Spanish and English.

All three choices are per browser: they are kept in `localStorage` under `review-studio.mode`, `review-studio.advanced` and `review-studio.locale`. They are never sent to the server, so a different browser or a cleared profile starts again as a first run. If storage is unavailable, the app still works and simply forgets the choice on reload.

## Run
npm install
npm run dev

Also available: npm run build, npm run typecheck, npm test, and npm run lint. Lint runs ESLint over the production TypeScript source.

For local development, `.env.development` points to the local sidecar at
`http://127.0.0.1:8765/v2`; start the sidecar with an explicit workspace before
running the app. For a self-hosted or authenticated deployment, override
`VITE_DOCS_API_BASE_URL` with that API's `/v2` URL and provide
`VITE_DOCS_API_TOKEN` when a bearer token is required. Remote API failures are
shown in the UI and never replaced with demo data.

Tests inject fetch-backed API clients; production and development always use the configured remote API. No external assets or router dependency is required.

Run the browser fixture tests with `npm run test:e2e`; they start a local API fixture and exercise sessions, findings, graph data, skip-link navigation, and visible focus.
