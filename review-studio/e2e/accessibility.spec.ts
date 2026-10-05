import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const routes = [
  "/", "/configure", "/configure/workspaces", "/configure/templates", "/configure/diagnostics", "/configure/plugins",
  ...["sources", "classification", "assets", "context", "sections", "revisions"].map(tab => `/authoring/${tab}`),
  "/pipeline",
  ...["findings", "artifacts", "evidence", "baselines", "diff", "qa", "graph"].map(tab => `/review/${tab}`),
  "/delivery", "/tools",
];

async function violations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  return violations.filter(item => item.impact === "serious" || item.impact === "critical")
    .map(item => `${item.id} (${item.impact}): ${item.nodes.slice(0, 3).map(node => node.target.join(" ")).join(" | ")}`);
}

async function settle(page: Page) {
  await expect(page.locator("main h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
}

for (const route of routes) {
  test(`axe: no serious or critical violations on ${route}`, async ({ page }) => {
    await page.goto(`/#${route}`);
    await settle(page);
    expect(await violations(page)).toEqual([]);
  });
}

test("axe: no serious or critical violations on a run detail", async ({ page }) => {
  await page.goto("/#/pipeline");
  await page.getByRole("table", { name: "Runs" }).getByRole("link").first().click();
  await expect(page.getByRole("heading", { name: /^Run / })).toBeVisible();
  await settle(page);
  expect(await violations(page)).toEqual([]);
});

test("axe: no serious or critical violations with the command palette open", async ({ page }) => {
  await page.goto("/#/");
  await settle(page);
  await page.keyboard.press("Control+K");
  await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  expect(await violations(page)).toEqual([]);
});
