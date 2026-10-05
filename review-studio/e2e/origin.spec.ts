import { expect, test } from "@playwright/test";

const api = "http://127.0.0.1:8765";
const allowed = "http://127.0.0.1:5173";
const evil = "http://evil.example";

test("the sidecar echoes CORS headers only for the configured origin", async ({ request }) => {
  const good = await request.get(`${api}/v2/workspaces`, { headers: { Origin: allowed } });
  expect(good.status()).toBe(200);
  expect(good.headers()["access-control-allow-origin"]).toBe(allowed);

  const bad = await request.get(`${api}/v2/workspaces`, { headers: { Origin: evil } });
  expect(bad.headers()["access-control-allow-origin"]).toBeUndefined();
  expect(bad.headers()["access-control-allow-credentials"]).toBeUndefined();
});

test("preflight is granted to the configured origin and refused to others", async ({ request }) => {
  const preflight = (origin: string) => request.fetch(`${api}/v2/documents`, { method: "OPTIONS", headers: { Origin: origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type" } });
  const good = await preflight(allowed);
  expect(good.headers()["access-control-allow-origin"]).toBe(allowed);
  const bad = await preflight(evil);
  expect(bad.headers()["access-control-allow-origin"]).toBeUndefined();
  expect(bad.ok(), "the preflight is rejected, not approved").toBe(false);
});

test("a page served from an unconfigured origin cannot read the API from the browser", async ({ page }) => {
  await page.route("http://evil.example/**", route => route.fulfill({ contentType: "text/html", body: "<title>evil</title>" }));
  await page.goto(`${evil}/`);
  const outcome = await page.evaluate(async url => { try { await fetch(url); return "readable"; } catch { return "blocked"; } }, `${api}/v2/workspaces`);
  expect(outcome).toBe("blocked");
});
