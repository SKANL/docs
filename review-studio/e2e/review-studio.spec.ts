import { expect, test } from "@playwright/test";

test("loads sessions, findings, and graph data from the local API fixture", async ({ page }) => {
  await page.goto("/#runs");
  await expect(page.getByRole("cell", { name: "fixture-session-1" })).toBeVisible();

  await page.getByRole("link", { name: "Findings inbox" }).click();
  await expect(page.getByRole("heading", { name: "Fixture finding" })).toBeVisible();

  await page.getByRole("link", { name: "Semantic graph" }).click();
  await expect(page.getByRole("img", { name: /semantic graph connecting/i })).toBeVisible();
  await expect(page.getByText("Fixture claim")).toBeVisible();
});

test("supports skip-link keyboard navigation and visible focus", async ({ page }) => {
  await page.goto("/#findings");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await expect(skip).toHaveCSS("outline-style", "solid");

  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  await expect(page.getByRole("textbox", { name: "Filter findings" })).toBeVisible();
});
