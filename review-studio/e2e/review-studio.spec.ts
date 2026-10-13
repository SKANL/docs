import { expect, test } from "@playwright/test";

test("renders real workspace, run, artifact, and provenance data", async ({ page }) => {
  await page.goto("/#/pipeline");
  await expect(page.getByRole("row", { name: /[0-9a-f]{8}-[0-9a-f]{4}-/i }).first()).toBeVisible();
  await expect(page.getByText(/Live progress|succeeded|passed|warnings/i).first()).toBeVisible();
  await page.getByRole("link", { name: "Review" }).click();
  await page.goto("/#/review/artifacts");
  await expect(page.getByRole("heading", { name: "Review", exact: true })).toBeVisible();
  await page.goto("/#/review/evidence");
  await expect(page.getByRole("region", { name: "Runs with evidence" })).toBeVisible();
});

test("Home shows the current document, recent runs and one next action", async ({ page }) => {
  await page.goto("/#/");
  await expect(page.getByRole("heading", { name: "Home", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Recent runs" }).getByRole("link").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Next safe action" }).getByRole("link")).toHaveCount(1);
});

test("supports skip-link keyboard navigation and visible focus", async ({ page }) => {
  test.setTimeout(60_000); // the first dev-server load compiles the app
  await page.goto("/#/");
  const skip = page.getByRole("link", { name: "Skip to content" });
  // Tab only once the shell has mounted; earlier presses land on the bare document.
  await expect(skip).toBeAttached();
  await page.keyboard.press("Tab");
  await expect(skip).toBeFocused();
  await expect(skip).toHaveCSS("outline-style", "solid");
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  await expect(page.getByRole("navigation", { name: "Task areas" })).toBeVisible();
});

test("selects a workspace through the shared lifecycle UI", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/#/configure/workspaces");
  await expect(page.getByRole("heading", { name: "Workspace and document control" })).toBeVisible();
  // Unique per run so a reused fixture never holds a previous run's workspace.
  const tag = `Browser journey ${Date.now()}`;
  const renamed = `${tag} renamed`;
  const workspaceSelect = page.getByRole("combobox", { name: "Active workspace" });
  const originalWorkspaceName = (await workspaceSelect.textContent())?.replace("⌄", "").trim() ?? "";

  await page.getByRole("button", { name: "Create workspace" }).click();
  const workspaceDialog = page.getByRole("dialog", { name: "Create workspace" });
  await workspaceDialog.getByRole("textbox", { name: "Workspace name" }).fill(tag);
  await workspaceDialog.getByRole("button", { name: "Create workspace" }).click();
  await expect(workspaceSelect).toContainText(tag);

  await page.getByRole("button", { name: "Rename workspace" }).click();
  const renameWorkspace = page.getByRole("dialog", { name: "Rename workspace" });
  await renameWorkspace.getByRole("textbox", { name: "Workspace name" }).fill(renamed);
  await renameWorkspace.getByRole("button", { name: "Rename workspace" }).click();
  await expect(workspaceSelect).toContainText(renamed);
  await workspaceSelect.click();
  await page.getByRole("option", { name: originalWorkspaceName, exact: true }).click();
  await expect(workspaceSelect).toContainText(originalWorkspaceName);
});

test("recovers from workspace rename errors and confirms workspace deletion", async ({ page }) => {
  test.setTimeout(60_000);
  let failRename = true;
  await page.route("**/v2/workspaces/*", async route => {
    if (route.request().method() === "PATCH" && failRename) {
      failRename = false;
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ code: "temporarily_unavailable", message: "Workspace service is temporarily unavailable" }) });
      return;
    }
    await route.continue();
  });
  await page.goto("/#/configure/workspaces");
  await expect(page.getByRole("heading", { name: "Workspace and document control" })).toBeVisible();

  await page.getByRole("button", { name: "Create workspace" }).click();
  const create = page.getByRole("dialog", { name: "Create workspace" });
  await create.getByRole("textbox", { name: "Workspace name" }).fill("Disposable workspace");
  await create.getByRole("button", { name: "Create workspace" }).click();
  const selector = page.getByRole("combobox", { name: "Active workspace" });
  await expect(selector).toContainText("Disposable workspace");

  await page.getByRole("button", { name: "Rename workspace" }).click();
  const rename = page.getByRole("dialog", { name: "Rename workspace" });
  await rename.getByRole("textbox", { name: "Workspace name" }).fill("Disposable renamed");
  await rename.getByRole("button", { name: "Rename workspace" }).click();
  await expect(rename.getByRole("alert")).toContainText("temporarily unavailable");
  await rename.getByRole("button", { name: "Rename workspace" }).click();
  await expect(selector).toContainText("Disposable renamed");

  await page.getByRole("button", { name: "Delete workspace" }).click();
  const deletion = page.getByRole("alertdialog", { name: "Delete workspace" });
  await deletion.getByRole("button", { name: "Cancel" }).click();
  await expect(selector).toContainText("Disposable renamed");
  await page.getByRole("button", { name: "Delete workspace" }).click();
  await page.getByRole("alertdialog", { name: "Delete workspace" }).getByRole("button", { name: "Delete workspace" }).click();
  await expect(selector).not.toContainText("Disposable renamed");
});

test("manages documents through the shared lifecycle UI", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/#/configure/workspaces");
  await expect(page.getByRole("heading", { name: "Workspace and document control" })).toBeVisible();
  await page.getByRole("button", { name: "Create document" }).click();
  const documentDialog = page.getByRole("dialog", { name: "Create document" });
  await documentDialog.getByRole("textbox", { name: "Document ID" }).fill("browser-journey");
  await documentDialog.getByRole("textbox", { name: "Title" }).fill("Browser journey document");
  await documentDialog.getByRole("button", { name: "Create document" }).click();
  const documentList = page.getByRole("list", { name: "Workspace documents" });
  await expect(documentList.getByText("Browser journey document")).toBeVisible();

  await page.getByRole("button", { name: "Create document" }).click();
  const secondDocumentDialog = page.getByRole("dialog", { name: "Create document" });
  await secondDocumentDialog.getByRole("textbox", { name: "Document ID" }).fill("browser-journey-second");
  await secondDocumentDialog.getByRole("textbox", { name: "Title" }).fill("Second browser document");
  await secondDocumentDialog.getByRole("button", { name: "Create document" }).click();
  await page.getByRole("button", { name: "Use browser-journey" }).click();
  await expect(page.getByRole("region", { name: "Document status" })).toContainText("Browser journey document");

  await page.getByRole("button", { name: "Rename browser-journey", exact: true }).click();
  const renameDialog = page.getByRole("dialog", { name: "Rename document" });
  await renameDialog.getByRole("textbox", { name: "New document ID" }).fill("browser-journey-renamed");
  await renameDialog.getByRole("button", { name: "Save name" }).click();
  await expect(documentList.getByText("browser-journey-renamed")).toBeVisible();

  await page.getByRole("button", { name: "Delete browser-journey-renamed" }).click();
  const deletion = page.getByRole("alertdialog", { name: "Delete document" });
  await deletion.getByRole("button", { name: "Cancel" }).click();
  await expect(documentList.getByText("browser-journey-renamed")).toBeVisible();
  await page.getByRole("button", { name: "Delete browser-journey-renamed" }).click();
  await page.getByRole("alertdialog", { name: "Delete document" }).getByRole("button", { name: "Delete document" }).click();
  await page.getByRole("button", { name: "Delete browser-journey-second" }).click();
  await page.getByRole("alertdialog", { name: "Delete document" }).getByRole("button", { name: "Delete document" }).click();
  // The shared fixture seeds browser-e2e, so assert the journey documents are gone rather than an empty list.
  await expect(documentList.getByText(/browser-journey/)).toHaveCount(0);
});
