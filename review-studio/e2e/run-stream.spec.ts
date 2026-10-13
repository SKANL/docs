import { expect, test } from "@playwright/test";

const frame = (id: string, message: string) => `event: progress\ndata: ${JSON.stringify({ type: "progress", progress: 42, message, run: { id, status: "running" } })}\n\n`;

test("leaving a run aborts its progress stream and its frames never reach the next run", async ({ page }) => {
  test.setTimeout(60_000);
  const seen: Record<string, { started: number; failed: number; finished: number }> = { "run-a": { started: 0, failed: 0, finished: 0 }, "run-b": { started: 0, failed: 0, finished: 0 } };
  const progressId = (url: string) => /\/runs\/(run-[ab])\/progress/.exec(url)?.[1];
  page.on("request", request => { const id = progressId(request.url()); if (id) seen[id].started += 1; });
  page.on("requestfailed", request => { const id = progressId(request.url()); if (id) seen[id].failed += 1; });
  page.on("requestfinished", request => { const id = progressId(request.url()); if (id) seen[id].finished += 1; });

  await page.route(/\/v2\/runs\/run-[ab](\?|$)/, route => {
    const id = /run-[ab]/.exec(route.request().url())![0];
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ id, status: "running", created_at: "2026-01-01T00:00:00Z", payload: { document_id: "browser-e2e", format: "html", pipeline_id: "document", policy: "draft" } }) });
  });
  // Run A sends one frame, then its stream stays open (the request is held) like a long-running run; run B stays open.
  let aServed = 0;
  await page.route(/\/runs\/run-[ab]\/progress/, route => {
    const id = progressId(route.request().url())!;
    if (id === "run-a" && aServed++ === 0) return route.fulfill({ contentType: "text/event-stream", body: frame("run-a", "frame-from-A") });
    return new Promise<void>(() => { /* held open: only an abort from the page ends it */ });
  });

  await page.goto("/#/pipeline/runs/run-a");
  await expect(page.getByRole("heading", { name: "Run run-a" })).toBeVisible();
  await expect(page.getByText("frame-from-A")).toBeVisible();
  await expect.poll(() => seen["run-a"].started).toBeGreaterThanOrEqual(2); // frame closed, client reconnected, second request is held

  await page.goto("/#/pipeline/runs/run-b");
  await expect(page.getByRole("heading", { name: "Run run-b" })).toBeVisible();
  await expect.poll(() => seen["run-b"].started).toBeGreaterThanOrEqual(1);
  await expect(page.getByText("frame-from-A")).toHaveCount(0);

  const startedAtSwitch = seen["run-a"].started;
  await page.waitForTimeout(2_500); // longer than the reconnect backoff: a leaked loop would have reopened A by now
  expect(seen["run-a"].started).toBe(startedAtSwitch);
  expect(seen["run-a"].failed + seen["run-a"].finished, "every A progress request ended").toBe(startedAtSwitch);
  await expect(page.getByText("frame-from-A")).toHaveCount(0);
  console.log("stream counters", JSON.stringify(seen));
});
