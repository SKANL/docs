import { expect, test, type Page } from "@playwright/test";

/** Diagnostics act on the current document; select the seeded one through the UI when it is not already current. */
async function ensureCurrentDocument(page: Page) {
  await page.goto("/#/tools");
  if (await page.getByRole("heading", { name: "Select a document first" }).isVisible()) {
    await page.getByRole("link", { name: "Open workspaces and documents" }).click();
    await page.getByRole("button", { name: "Use browser-e2e" }).click();
    await expect(page.getByRole("button", { name: "Current" })).toBeVisible();
  }
}

test("lists the diagnostic checks of the real sidecar", async ({ page }) => {
  await ensureCurrentDocument(page);
  await page.goto("/#/configure/diagnostics");
  const table = page.getByRole("table", { name: "Diagnostic checks" });
  await expect(table).toBeVisible({ timeout: 60_000 });
  await expect(table.getByRole("row")).not.toHaveCount(1);
  await expect(table).toContainText(/ok|warn|error|unavailable/);
});

test("validates an installed template and shows the outcome", async ({ page }) => {
  await page.goto("/#/configure/templates");
  const row = page.getByRole("table", { name: "Built-in catalogue" }).getByRole("row", { name: /documento-generico/ });
  await expect(row).toBeVisible();
  if (await row.getByText("Not installed").isVisible()) {
    await page.getByRole("button", { name: "Install documento-generico" }).click();
    await expect(row.getByText("Installed", { exact: true })).toBeVisible();
  }
  await page.getByRole("textbox", { name: "Template name", exact: true }).fill("documento-generico");
  await page.getByRole("button", { name: "Validate", exact: true }).click();
  const result = page.getByRole("status", { name: "Validation result" });
  await expect(result).toBeVisible();
  await expect(result).toContainText(/Passed|Issues found/);
});

test("explains a known issue code", async ({ page }) => {
  await page.goto("/#/configure/diagnostics");
  await page.getByRole("textbox", { name: "Issue code" }).fill("accessibility.pdf.language_missing");
  await page.getByRole("button", { name: "Explain code" }).click();
  const explanation = page.getByRole("region", { name: "Issue code explanation" });
  await expect(explanation).toBeVisible();
  await expect(explanation).toContainText("accessibility.pdf.language_missing");
  await expect(explanation).toContainText("Meaning");
});
