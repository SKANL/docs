// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, ReviewApiClient } from "../api/client";

const json = (body: unknown, init: ResponseInit = {}) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" }, ...init });
const setup = (response: () => Response) => {
  const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => response());
  return { fetcher, client: new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher }) };
};
const call = (fetcher: ReturnType<typeof setup>["fetcher"], index = 0) => {
  const [input, init] = fetcher.mock.calls[index] as [RequestInfo | URL, RequestInit | undefined];
  const url = new URL(input.toString());
  return { path: url.pathname, query: Object.fromEntries(url.searchParams), method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined };
};

describe("quality client", () => {
  beforeEach(() => { localStorage.setItem("docs.review.workspace", "workspace-1"); });

  it("reads a run evidence bundle and accepts either digest spelling", async () => {
    const raw = { run_id: "run 1", evidence_sha256: "e".repeat(64), passport: { entries: [] }, findings: [{ id: "f1" }],
      artifacts: [{ id: "a1", kind: "docx", digest: "d1", media_type: "application/x" }, { id: "a2", kind: "png", sha256: "d2", media_type: "image/png" }] };
    const { client, fetcher } = setup(() => json(raw));
    const bundle = await client.quality.getRunEvidence("run 1");
    expect(call(fetcher)).toMatchObject({ method: "GET", path: "/v2/runs/run%201/evidence", query: { workspace_id: "workspace-1" } });
    expect(bundle.artifacts.map(a => a.digest)).toEqual(["d1", "d2"]);
    // The server may omit preview availability; it is derived from PNG artifacts.
    expect(bundle.previews).toEqual({ available: true, artifact_ids: ["a2"] });
  });

  it("promotes a baseline with only the chosen fields", async () => {
    const result = { run_id: "r1", name: "main", destination: "baselines/main", replaced: false, pages: [{ name: "p1.png", sha256: "x" }] };
    const { client, fetcher } = setup(() => json(result, { status: 201 }));
    await expect(client.quality.promoteBaseline({ runId: "r1", name: "main" })).resolves.toEqual(result);
    expect(call(fetcher)).toMatchObject({ method: "POST", path: "/v2/baselines/promotions", query: { workspace_id: "workspace-1" }, body: { run_id: "r1", name: "main" } });
    expect(call(fetcher).body).not.toHaveProperty("update");
  });

  it("keeps the server error code of a refused promotion", async () => {
    const { client } = setup(() => json({ error: { code: "baseline_exists", message: "Baseline already exists; pass update to replace it" } }, { status: 409 }));
    const error = await client.quality.promoteBaseline({ runId: "r1" }).catch(e => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "baseline_exists" });
  });

  it("inspects and diffs artifacts", async () => {
    const report = { path: "out/a.html", media_type: "text/html", sha256: "s", size_bytes: 10 };
    const { client, fetcher } = setup(() => json({ artifact_id: "a1", ...report }));
    await client.quality.inspectArtifact("a 1");
    expect(call(fetcher)).toMatchObject({ method: "GET", path: "/v2/artifacts/a%201/inspect" });
    const diff = { same: false, left: report, right: report, text_diff: ["-a", "+b"] };
    const second = setup(() => json(diff));
    await expect(second.client.quality.diffArtifacts("a1", "a2")).resolves.toEqual(diff);
    expect(call(second.fetcher)).toMatchObject({ method: "POST", path: "/v2/artifacts/diff", body: { left: "a1", right: "a2" } });
  });

  it("runs qa-docx and normalises the degraded reason", async () => {
    const { client, fetcher } = setup(() => json({ document_id: "d", docx: "o.docx", strict: true, passed: false, message: "no render", degraded: true, reason: "LibreOffice not found", report: null }));
    const result = await client.quality.runQaDocx("doc 1", { strict: true });
    expect(call(fetcher)).toMatchObject({ method: "POST", path: "/v2/documents/doc%201/qa-docx", body: { strict: true } });
    expect(result).toMatchObject({ degraded: true, degraded_reason: "LibreOffice not found" });
  });

  it("applies corrections", async () => {
    const { client, fetcher } = setup(() => json({ document_id: "d", applied: 3 }));
    await expect(client.quality.applyCorrections("d")).resolves.toEqual({ document_id: "d", applied: 3 });
    expect(call(fetcher)).toMatchObject({ method: "POST", path: "/v2/documents/d/corrections/apply" });
  });
});
