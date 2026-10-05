// Drive the real Tauri/WebView2 runtime over CDP: launch the built desktop exe,
// attach, and exercise the shared Review Studio workspace/document journey on a
// fresh install. Build the exe first with `npm run build:runtime-check`.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, rmSync, mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const desktop = resolve(fileURLToPath(new URL("..", import.meta.url)));
const exe = process.argv.slice(2).find(a => !a.startsWith("--")) ?? join(desktop, "src-tauri", "target", "release", "docs-desktop.exe");
const reviewStudioDir = join(desktop, "..", "review-studio");
const port = process.env.DESKTOP_RUNTIME_CDP_PORT ?? "9333";
// The check creates and deletes its own document in the app-data workspace. Refuse
// to run against an existing install so it can never touch a user's real data.
const appData = join(process.env.APPDATA ?? "", "com.docs.reviewstudio");
const marker = join(appData, ".runtime-check-owned");
// --fresh: delete the data dir ONLY when this script created it (marker present).
if (process.argv.includes("--fresh") && existsSync(appData)) {
  if (!existsSync(marker)) { console.error(`[desktop-runtime] --fresh refused: ${appData} has no .runtime-check-owned marker (not created by this check).`); process.exit(2); }
  rmSync(appData, { recursive: true, force: true });
}
const freshRun = !existsSync(appData);
if (existsSync(appData) && process.env.DESKTOP_RUNTIME_ALLOW_EXISTING_APPDATA !== "1") {
  console.error(`[desktop-runtime] ${appData} exists; refusing to run against existing desktop data. Re-run with --fresh only if a previous run of this check created it.`);
  process.exit(2);
}
if (!existsSync(exe)) { console.error(`[desktop-runtime] desktop executable not found: ${exe}`); process.exit(2); }
const require = createRequire(`${reviewStudioDir}/package.json`);
const { chromium } = require("@playwright/test");
// Claim the dir we are about to create so a later --fresh may remove it.
if (freshRun) { mkdirSync(appData, { recursive: true }); writeFileSync(marker, "created by check-desktop-runtime.mjs"); }
const app = spawn(exe, [], { env: { ...process.env, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port}` }, stdio: "inherit" });
const kill = () => spawnSync("taskkill", ["/PID", String(app.pid), "/T", "/F"], { stdio: "ignore" });
const log = (...a) => console.log("[desktop-runtime]", ...a);
try {
  let browser;
  for (let i = 0; i < 120 && !browser; i++) {
    try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`); } catch { await new Promise(r => setTimeout(r, 500)); }
  }
  if (!browser) throw new Error("WebView2 CDP endpoint never came up");
  let page;
  for (let i = 0; i < 60 && !page; i++) { page = browser.contexts().flatMap(c => c.pages())[0]; if (!page) await new Promise(r => setTimeout(r, 500)); }
  if (!page) throw new Error("WebView2 attached but no page appeared within 30s");
  for (let i = 0; i < 120 && !/tauri\.localhost/.test(page.url()); i++) await new Promise(r => setTimeout(r, 500));
  if (!/tauri\.localhost/.test(page.url())) throw new Error(`WebView never navigated to tauri.localhost (stuck at ${page.url()})`);
  await page.waitForLoadState("load");
  log("url", page.url(), "tauri", await page.evaluate(() => "__TAURI_INTERNALS__" in window));
  await page.waitForFunction(() => document.body.innerText.includes("Review Studio"), null, { timeout: 30000 });
  await page.evaluate(() => { location.hash = "#workspace"; });
  const heading = page.getByRole("heading", { name: "Workspace and document control" });
  await heading.waitFor({ timeout: 90000 });
  log("workspace page visible");
  const docId = `tauri-runtime-${Date.now()}`;
  await page.getByRole("button", { name: "Create document" }).first().waitFor({ timeout: 90000 });
  await page.getByRole("button", { name: "Create document" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Create document" });
  await dialog.getByRole("textbox", { name: "Document ID" }).fill(docId);
  await dialog.getByRole("textbox", { name: "Title" }).fill("Tauri runtime document");
  await dialog.getByRole("button", { name: "Create document" }).click();
  const list = page.getByRole("list", { name: "Workspace documents" });
  await list.getByText("Tauri runtime document").waitFor({ timeout: 60000 });
  log("document created in desktop runtime:", docId);
  await page.getByRole("button", { name: `Delete ${docId}` }).click();
  await page.getByRole("alertdialog", { name: "Delete document" }).getByRole("button", { name: "Cancel" }).click();
  await list.getByText("Tauri runtime document").waitFor();
  log("delete cancellation kept document");
  await page.getByRole("button", { name: `Delete ${docId}` }).click();
  await page.getByRole("alertdialog", { name: "Delete document" }).getByRole("button", { name: "Delete document" }).click();
  await list.getByText("Tauri runtime document").waitFor({ state: "detached", timeout: 60000 });
  log("document deleted after confirmation");
  await page.screenshot({ path: process.env.DESKTOP_RUNTIME_SCREENSHOT ?? "desktop-runtime.png" });
  log("PASS");
  await browser.close();
} catch (error) {
  console.error("[desktop-runtime] FAIL", String(error).slice(0, 600));
  try { const pg = (await chromium.connectOverCDP(`http://127.0.0.1:${port}`)).contexts()[0].pages()[0]; console.error("[desktop-runtime] body:", (await pg.innerText("body")).slice(0, 1500)); await pg.screenshot({ path: (process.env.DESKTOP_RUNTIME_SCREENSHOT ?? "desktop-runtime.png").replace(".png", "-fail.png") }); } catch {}
  process.exitCode = 1;
} finally { kill(); }
