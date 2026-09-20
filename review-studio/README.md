# Review Studio

Standalone browser-first React + TypeScript + Vite foundation for reviewing document runs, evidence, artifacts, and publication readiness.

## Run
npm install
npm run dev

Also available: npm run build, npm run typecheck, npm test, and npm run lint. There is no lint configuration yet; the lint script is intentionally a documented no-op while the foundation is being established.

The app uses hash navigation and a deterministic typed mock adapter in src/api, modeled on the harness /v1 concepts. No external assets or router dependency is required.
