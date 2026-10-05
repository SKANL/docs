import { expect, test } from "@playwright/test";

test("follows the seeded run to its evidence, inspects an artifact, and promotes (or honestly refuses) a baseline", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/#/review/evidence");
  await expect(page.getByRole("heading", { name: "Review", exact: true })).toBeVisible();

  // Specs share one fixture, so later specs add runs; pick a run that succeeded and therefore has artifacts.
  const runs = page.getByRole("region", { name: "Runs with evidence" });
  await expect(runs).toBeVisible();
  await runs.getByRole("listitem").filter({ hasText: "succeeded" }).first().getByRole("link").click();
  await expect(page.getByRole("heading", { name: /^Evidence for / })).toBeVisible();
  const digest = page.getByRole("region", { name: "Evidence digest" });
  await expect(digest).toContainText(/[0-9a-f]{64}/);
  await expect(page.getByRole("region", { name: "Passport summary" })).toBeVisible();

  // Open an artifact from the run and inspect it: a structured report with a digest, never raw JSON.
  const artifactLink = page.getByRole("table", { name: "Run artifacts" }).getByRole("link").first();
  await artifactLink.click();
  await expect(page.getByRole("region", { name: "Artifact detail" })).toBeVisible();
  await page.getByRole("button", { name: "Inspect artifact" }).click();
  const inspection = page.getByRole("region", { name: "Inspection" });
  await expect(inspection).toContainText(/[0-9a-f]{64}/);
  await expect(inspection).toContainText("Media type");
  // Previews are either shown or honestly reported missing.
  await expect(page.getByRole("region", { name: "Previews" })).toContainText(/Page preview|No rendered previews|Preview image unavailable|could not be loaded/);

  // Promote a baseline: success when PNG previews exist, otherwise the server's refusal is shown as-is.
  await page.goBack();
  await page.getByRole("button", { name: "Promote to baseline" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Promote baseline" }).click();
  await expect(dialog).toContainText(/Saved a new baseline|no rendered previews|already exists|spread over several/i);
});
