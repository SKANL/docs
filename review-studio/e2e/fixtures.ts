import { test as base } from "@playwright/test";

/** English, mode chosen, Advanced on: the full app the specs were written against. modes.spec.ts uses the bare test instead. */
export const test = base.extend({
  page: async ({ page }, use) => {
    await page.addInitScript(() => {
      localStorage.setItem("review-studio.locale", "en");
      localStorage.setItem("review-studio.mode", "write");
      localStorage.setItem("review-studio.advanced", "true");
    });
    await use(page);
  },
});
export { expect } from "@playwright/test";
