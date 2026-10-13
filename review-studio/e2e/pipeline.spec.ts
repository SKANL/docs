import { expect, test } from "@playwright/test";

test("lists the seeded run, opens its receipt, and watches a new html run to the end", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/#/pipeline");
  await expect(page.getByRole("heading", { name: "Pipeline", exact: true })).toBeVisible();

  // The fixture seeds one completed run for browser-e2e; history does not need a current document.
  const table = page.getByRole("table", { name: "Runs" });
  await expect(table).toBeVisible();
  await expect(table.getByRole("row")).not.toHaveCount(1);
  await expect(table).toContainText("browser-e2e");
  await table.getByRole("link").first().click();
  await expect(page.getByRole("heading", { name: /^Run / })).toBeVisible();
  await expect(page.getByRole("region", { name: "Run receipt" })).toContainText("succeeded");
  await expect(page.getByRole("region", { name: "Run summary" })).toContainText("browser-e2e");

  // Launching needs a current document; select the seeded one through the UI when it is not already current.
  await page.goto("/#/pipeline");
  if (await page.getByRole("heading", { name: "Select a document first" }).isVisible()) {
    await page.getByRole("link", { name: "Open workspaces and documents" }).click();
    await page.getByRole("button", { name: "Use browser-e2e" }).click();
    await expect(page.getByRole("button", { name: "Current" })).toBeVisible();
    await page.goto("/#/pipeline");
  }
  await expect(page.getByRole("region", { name: "Active context" })).toContainText("browser-e2e");
  await expect(page.getByRole("list", { name: "Pipeline stages" })).toBeVisible();

  await page.getByRole("combobox", { name: "Output format" }).click();
  await page.getByRole("option", { name: "html" }).click();
  await page.getByRole("button", { name: "Run pipeline" }).click();

  // The new run opens on its own page and reaches a terminal receipt through the progress stream.
  await expect(page.getByRole("heading", { name: /^Run / })).toBeVisible();
  await expect(page.getByRole("region", { name: "Run receipt" })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("region", { name: "Run receipt" })).toContainText("Final status");

  // Back on the pipeline page the new run is in the history.
  await page.getByRole("link", { name: "Back to pipeline" }).click();
  await expect(page.getByRole("table", { name: "Runs" }).getByRole("row")).not.toHaveCount(2);
});
