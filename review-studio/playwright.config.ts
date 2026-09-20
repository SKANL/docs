import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:5173", ...devices["Desktop Chrome"] },
  webServer: [
    { command: "node e2e/api-fixture.mjs", url: "http://127.0.0.1:4174/v1/runs", reuseExistingServer: true },
    { command: "npm run dev -- --host 127.0.0.1", url: "http://127.0.0.1:5173", reuseExistingServer: true, env: { VITE_DOCS_API_BASE_URL: "http://127.0.0.1:4174/v1", VITE_REVIEW_STUDIO_MOCK_API: "false" } },
  ],
});
