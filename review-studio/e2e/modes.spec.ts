import { expect, test } from "@playwright/test";

// Bare Playwright test: a fresh browser context has no stored locale, mode or Advanced flag, i.e. a first run.

const nav = (page: import("@playwright/test").Page) => page.getByRole("navigation", { name: "Áreas de trabajo" }).getByRole("link");

test("first run is Spanish with exactly the four base areas", async ({ page }) => {
  await page.goto("/#/");
  await expect(nav(page)).toHaveText(["Inicio", "Generar", "Revisar", "Entregar"]);
});

test("Advanced reveals the technical areas", async ({ page }) => {
  await page.goto("/#/");
  await expect(nav(page)).toHaveCount(4);
  await page.getByRole("switch", { name: "Avanzado" }).click();
  await expect(nav(page)).toHaveText(["Inicio", "Generar", "Revisar", "Entregar", "Configuración técnica"]);
  await expect(page.getByRole("navigation", { name: "Herramientas especializadas" }).getByRole("link", { name: "Herramientas" })).toBeVisible();
});

test("first-run chooser on Home picks a mode once; Write adds its area", async ({ page }) => {
  await page.goto("/#/");
  const chooser = page.getByRole("group", { name: "¿Cómo quieres trabajar?" });
  await expect(chooser).toBeVisible();
  await chooser.getByRole("button", { name: /Redactar/ }).click();
  await expect(chooser).toBeHidden();
  await expect(nav(page)).toHaveText(["Inicio", "Redactar", "Generar", "Revisar", "Entregar"]);
  await page.reload();
  await expect(chooser).toBeHidden();
});
