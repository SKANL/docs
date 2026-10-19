import { expect, test } from "./fixtures";

test("keyboard only: skip link, command palette, and focus return", async ({ page }) => {
  await page.goto("/#/");
  await expect(page.getByRole("heading", { name: "Home", exact: true })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();

  // Esc closes the palette and puts focus back where it was.
  const nav = page.getByRole("navigation", { name: "Task areas" }).getByRole("link").first();
  await nav.focus();
  await page.keyboard.press("Control+K");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  await expect(nav).toBeFocused();

  // Typing narrows the list and Enter navigates.
  await page.keyboard.press("Control+K");
  await page.keyboard.type("Write");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/authoring/);
  await expect(page.getByRole("heading", { name: "Authoring" })).toBeVisible();
  await expect(page.locator("#main")).toBeFocused();
});

test("keyboard only: focus is always visible", async ({ page }) => {
  await page.goto("/#/");
  await expect(page.getByRole("heading", { name: "Home", exact: true })).toBeVisible();
  for (let step = 0; step < 6; step += 1) {
    await page.keyboard.press("Tab");
    const style = await page.evaluate(() => {
      const active = document.activeElement as HTMLElement;
      const computed = getComputedStyle(active);
      return { tag: active.tagName, outline: computed.outlineStyle, width: parseFloat(computed.outlineWidth), shadow: computed.boxShadow };
    });
    expect((style.outline !== "none" && style.width >= 2) || style.shadow !== "none", `focus ring on ${style.tag} after ${step + 1} tabs`).toBe(true);
  }
});

test("keyboard only: create a document, cancel a delete with Esc, then confirm it", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/#/configure/workspaces");
  await expect(page.getByRole("heading", { name: "Workspace and document control" })).toBeVisible();
  const documentList = page.getByRole("list", { name: "Workspace documents" });

  const create = page.getByRole("button", { name: "Create document" });
  await expect(create).toBeEnabled(); // a busy page disables it, and a disabled button cannot take focus
  await create.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Create document" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("textbox", { name: "Document ID" })).toBeFocused(); // typing before focus lands drops characters
  await page.keyboard.type("kbd-journey");
  await page.keyboard.press("Tab");
  await page.keyboard.type("Keyboard journey");
  await page.keyboard.press("Enter"); // submits the form
  await expect(dialog).toBeHidden();
  await expect(documentList.getByText("Keyboard journey")).toBeVisible();

  const trigger = page.getByRole("button", { name: "Delete kbd-journey" });
  await expect(trigger).toBeEnabled();
  await trigger.focus();
  await page.keyboard.press("Enter");
  const confirm = page.getByRole("alertdialog", { name: "Delete document" });
  await expect(confirm).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(confirm).toBeHidden();
  await expect(trigger).toBeFocused();
  await expect(documentList.getByText("Keyboard journey")).toBeVisible();

  await page.keyboard.press("Enter");
  await expect(confirm).toBeVisible();
  await page.keyboard.press("Tab"); // Cancel -> Delete document
  await expect(confirm.getByRole("button", { name: "Delete document" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(documentList.getByText("Keyboard journey")).toHaveCount(0);
});

test("a failed destructive action keeps the dialog open with the server error and returns focus on cancel", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/#/configure/workspaces");
  await expect(page.getByRole("heading", { name: "Workspace and document control" })).toBeVisible();
  const documentList = page.getByRole("list", { name: "Workspace documents" });
  await page.getByRole("button", { name: "Create document" }).click();
  const dialog = page.getByRole("dialog", { name: "Create document" });
  await dialog.getByRole("textbox", { name: "Document ID" }).fill("kbd-failure");
  await dialog.getByRole("textbox", { name: "Title" }).fill("Failure journey");
  await dialog.getByRole("button", { name: "Create document" }).click();
  await expect(documentList.getByText("Failure journey")).toBeVisible();

  let fail = true;
  await page.route("**/v2/documents/kbd-failure*", async route => {
    if (route.request().method() === "DELETE" && fail) {
      fail = false;
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "conflict", message: "Document is locked by another run" } }) });
    } else await route.continue();
  });
  const trigger = page.getByRole("button", { name: "Delete kbd-failure" });
  await expect(trigger).toBeEnabled();
  await trigger.focus();
  await page.keyboard.press("Enter");
  const confirm = page.getByRole("alertdialog", { name: "Delete document" });
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(confirm.getByRole("alert")).toContainText("locked by another run");
  await page.keyboard.press("Escape");
  await expect(confirm).toBeHidden();
  await expect(trigger).toBeFocused();

  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(documentList.getByText("Failure journey")).toHaveCount(0);
});
