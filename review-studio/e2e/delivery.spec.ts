import { expect, test } from "@playwright/test";

test("packages, is denied a draft publish by the server, and opens the publication history", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/#/delivery");
  // Delivery acts on the current document; select the seeded one through the UI when it is not already current.
  if (await page.getByRole("heading", { name: "Select a document first" }).isVisible()) {
    await page.getByRole("link", { name: "Open workspaces and documents" }).click();
    await page.getByRole("button", { name: "Use browser-e2e" }).click();
    await expect(page.getByRole("button", { name: "Current" })).toBeVisible();
    await page.goto("/#/delivery");
  }
  await expect(page.getByRole("region", { name: "Active context" })).toContainText("browser-e2e");

  // Package: either a digest or the server's honest refusal when there is no build output; never a silent success.
  await page.getByRole("button", { name: "Package" }).click();
  const packageDialog = page.getByRole("dialog", { name: "Package" });
  await packageDialog.getByRole("button", { name: "Create package" }).click();
  await expect(packageDialog.getByRole("status", { name: "Package result" }).or(packageDialog.getByRole("alert"))).toBeVisible({ timeout: 30_000 });
  if (await packageDialog.getByRole("status", { name: "Package result" }).isVisible()) {
    await expect(packageDialog.getByRole("status", { name: "Package result" })).toContainText(/[0-9a-f]{64}/);
  }
  await packageDialog.getByRole("button", { name: "Close" }).click();

  // Publish with the draft policy: the server decides, and its reason is shown verbatim without any success claim.
  // The seeded fixture has no build output, so the server answers with its honest 409 (publish_source_unavailable)
  // before policy is evaluated; the policy denial itself is pinned in the Vitest feature tests.
  await page.getByRole("button", { name: "Publish" }).click();
  const publishDialog = page.getByRole("dialog", { name: "Publish" });
  await publishDialog.getByRole("textbox", { name: "Destination" }).fill("e2e/final.html");
  await publishDialog.getByRole("combobox", { name: "Policy" }).click();
  await page.getByRole("option", { name: "draft" }).click();
  await publishDialog.getByRole("button", { name: "Review publish" }).click();
  await expect(publishDialog).toContainText("e2e/final.html");
  await publishDialog.getByRole("button", { name: "Confirm and publish" }).click();
  await expect(publishDialog.getByRole("alert")).toBeVisible({ timeout: 30_000 });
  await expect(publishDialog.getByRole("alert")).toContainText(/build it first|policy|denied/i);
  await expect(page.getByRole("status", { name: "Publication result" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(publishDialog).toBeHidden();

  // History opens even when nothing was published.
  await expect(page.getByRole("region", { name: "Publication history" })).toBeVisible();
});
