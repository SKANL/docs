import { expect, test } from "@playwright/test";

test("renders real workspace, run, artifact, and provenance data", async ({ page }) => {
  await page.goto("/#runs");
  await expect(page.getByRole("row", { name: /[0-9a-f]{8}-[0-9a-f]{4}-/i })).toBeVisible();
  await expect(page.getByText(/Live progress|succeeded|passed|warnings/i).first()).toBeVisible();
  await page.getByRole("link", { name: "Artifact preview" }).click();
  await expect(page.getByRole("heading", { name: "Artifact & page preview" })).toBeVisible();
  await page.getByRole("link", { name: "Evidence passport" }).click();
  await expect(page.getByRole("heading", { name: "Evidence passport" })).toBeVisible();
});

test("supports skip-link keyboard navigation and visible focus", async ({ page }) => {
  await page.goto("/#overview");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await expect(skip).toHaveCSS("outline-style", "solid");
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  await expect(page.getByText("Workspace setup")).toBeVisible();
});
