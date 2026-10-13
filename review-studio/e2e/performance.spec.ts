import { expect, test } from "@playwright/test";

const BUDGET_MS = 3_000;

// Navigation start to a visible Home heading, against the real sidecar fixture (dev server, so a ceiling, not a production figure).
test("Home is usable within the time budget", async ({ page }) => {
  const samples: number[] = [];
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const started = Date.now();
    await page.goto("/#/", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: "Home", exact: true })).toBeVisible({ timeout: BUDGET_MS });
    samples.push(Date.now() - started);
    await page.goto("about:blank");
  }
  console.log(`home time-to-heading ms: ${samples.join(", ")}`);
  expect(Math.min(...samples)).toBeLessThan(BUDGET_MS);
  expect(Math.max(...samples)).toBeLessThan(BUDGET_MS);
});
