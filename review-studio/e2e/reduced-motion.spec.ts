import { expect, test, type Page } from "@playwright/test";

test.use({ reducedMotion: "reduce" });

/** Longest CSS animation/transition duration (ms) inside `selector`, plus how many animations are still running there. */
async function motion(page: Page, selector: string) {
  return page.evaluate(selector => {
    const roots = [...document.querySelectorAll(selector)];
    const nodes = roots.flatMap(root => [root, ...root.querySelectorAll("*")]);
    const ms = (value: string) => Math.max(0, ...value.split(",").map(part => parseFloat(part) * (part.trim().endsWith("ms") ? 1 : 1000)));
    const longest = Math.max(0, ...nodes.flatMap(node => { const style = getComputedStyle(node); return [ms(style.animationDuration), ms(style.transitionDuration)]; }));
    const running = roots.flatMap(root => root.getAnimations({ subtree: true })).filter(animation => animation.playState === "running" && Number(animation.effect?.getComputedTiming().duration ?? 0) > 1).length;
    return { roots: roots.length, longest, running };
  }, selector);
}

test("dialogs run no animation or transition longer than ~0 under prefers-reduced-motion", async ({ page }) => {
  await page.goto("/#/configure/workspaces");
  await expect(page.getByRole("button", { name: "Create document" })).toBeVisible();
  await page.getByRole("button", { name: "Create document" }).click();
  await expect(page.getByRole("dialog", { name: "Create document" })).toBeVisible();
  const result = await motion(page, "[role=dialog]");
  expect(result.roots).toBeGreaterThan(0);
  expect(result.longest).toBeLessThanOrEqual(1);
  expect(result.running).toBe(0);
});

test("toasts run no animation or transition longer than ~0 under prefers-reduced-motion", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/#/authoring/context");
  if (await page.getByRole("heading", { name: "Select a document first" }).isVisible()) {
    await page.getByRole("link", { name: "Open workspaces and documents" }).click();
    await page.getByRole("button", { name: "Use browser-e2e" }).click();
    await expect(page.getByRole("button", { name: "Current" })).toBeVisible();
    await page.goto("/#/authoring/context");
  }
  await page.getByRole("button", { name: /^Set value for / }).first().click();
  await page.getByRole("textbox", { name: "Value" }).fill("Atlas");
  await page.getByRole("button", { name: "Set context value" }).click();
  await expect(page.locator("[data-sonner-toast]").first()).toBeVisible();
  const result = await motion(page, "[data-sonner-toast]");
  expect(result.roots).toBeGreaterThan(0);
  expect(result.longest).toBeLessThanOrEqual(1);
  expect(result.running).toBe(0);
});
