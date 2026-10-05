import { expect, test } from "@playwright/test";

test("authors the seeded document through the real sidecar", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/#/authoring/sections");
  await expect(page.getByRole("heading", { name: "Authoring" })).toBeVisible();

  // Select the seeded document through the UI when it is not already current.
  if (await page.getByRole("heading", { name: "Select a document first" }).isVisible()) {
    await page.getByRole("link", { name: "Open workspaces and documents" }).click();
    await page.getByRole("button", { name: "Use browser-e2e" }).click();
    await expect(page.getByRole("button", { name: "Current" })).toBeVisible();
    await page.goto("/#/authoring/sections");
  }
  await expect(page.getByRole("region", { name: "Active context" })).toContainText("browser-e2e");

  // Sections: the real sections are listed and editable; review runs for the whole document.
  await expect(page.getByRole("navigation", { name: "Sections" }).getByRole("button")).not.toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Section body" })).toBeVisible();
  await page.getByRole("button", { name: "Review document" }).click();
  await expect(page.getByRole("region", { name: "Review findings" })).toBeVisible();

  // Context: set a value for the first declared topic.
  await page.getByRole("tab", { name: "Context" }).click();
  await page.getByRole("button", { name: /^Set value for / }).first().click();
  await page.getByRole("textbox", { name: "Value" }).fill("Atlas");
  await page.getByRole("button", { name: "Set context value" }).click();
  await expect(page.getByText(/^Saved context for /)).toBeVisible();

  // Assets: add, then remove with confirmation.
  await page.getByRole("tab", { name: "Assets" }).click();
  await page.getByLabel("Asset file").setInputFiles({ name: "e2e-cover.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: Buffer.from("PK00030004e2e") });
  await page.getByRole("button", { name: "Add asset" }).click();
  await expect(page.getByRole("button", { name: /^Remove e2e-cover/ })).toBeVisible();
  await page.getByRole("button", { name: /^Remove e2e-cover/ }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Remove asset" }).click();
  await expect(page.getByRole("button", { name: /^Remove e2e-cover/ })).toHaveCount(0);
});

// Blocked by a server contract gap, not by the UI: GET /sections reports each section id as the file stem
// ("020-introduccion") while save/build/review-section/stamp only accept the template id ("introduccion").
// Un-fixme once the sections listing carries the template section id.
test.fixme("edits and saves a section through the real sidecar", async ({ page }) => {
  await page.goto("/#/authoring/sections");
  await page.getByRole("button", { name: /introduccion/ }).click();
  await page.getByRole("textbox", { name: "Section body" }).fill("Edited through the authoring workspace.");
  await page.getByRole("button", { name: "Save section" }).click();
  await expect(page.getByText(/^Saved section /)).toBeVisible();
});
