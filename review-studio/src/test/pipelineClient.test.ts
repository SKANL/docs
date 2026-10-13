// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, ReviewApiClient } from "../api/client";
import { toRunRecord } from "../api/domains/pipeline";

const json = (body: unknown, init: ResponseInit = {}) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" }, ...init });
const sse = (...records: string[]) => new Response(new ReadableStream({ start(c) { records.forEach(r => c.enqueue(new TextEncoder().encode(r))); c.close(); } }), { status: 200, headers: { "content-type": "text/event-stream" } });
const setup = (response: () => Response) => {
  const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => response());
  return { fetcher, client: new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher }) };
};
const call = (fetcher: ReturnType<typeof setup>["fetcher"], index = 0) => {
  const [input, init] = fetcher.mock.calls[index] as [RequestInfo | URL, RequestInit | undefined];
  const url = new URL(input.toString());
  return { url, path: url.pathname, query: Object.fromEntries(url.searchParams), method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined };
};

describe("pipeline client", () => {
  beforeEach(() => { localStorage.setItem("docs.review.workspace", "workspace-1"); });

  it("plans a pipeline with a scoped POST", async () => {
    const plan = { document_id: "doc 1", pipeline_id: "document", stages: ["prepare", "build"], external_artifacts: ["inbox"], contracts: [] };
    const { client, fetcher } = setup(() => json(plan));
    await expect(client.pipeline.planPipeline("doc 1", { format: "html" })).resolves.toEqual(plan);
    expect(call(fetcher)).toMatchObject({ method: "POST", path: "/v2/documents/doc%201/plan", query: { workspace_id: "workspace-1" }, body: { format: "html" } });
  });

  it("runs a document and sends only the fields that were chosen", async () => {
    const started = { id: "run-1", status: "queued", document_id: "doc-1", pipeline_id: "document", format: "pdf", policy: "strict", links: { self: "/v2/runs/run-1", progress: "/v2/runs/run-1/progress", cancel: "/v2/runs/run-1/cancel" } };
    const { client, fetcher } = setup(() => json(started, { status: 202 }));
    await expect(client.pipeline.runDocument("doc-1", { format: "pdf", policy: "strict" })).resolves.toEqual(started);
    expect(call(fetcher)).toMatchObject({ method: "POST", path: "/v2/documents/doc-1/run", query: { workspace_id: "workspace-1" }, body: { format: "pdf", policy: "strict" } });
  });

  it("lists a page of runs with filters and a cursor", async () => {
    const raw = { id: "run-9", status: "failed", created_at: "2026-01-01T00:00:00Z", payload: { document_id: "doc-1", format: "html", policy: "draft", progress: { percent: 40, stage: "build" } } };
    const { client, fetcher } = setup(() => json({ items: [raw], next_cursor: "c2" }));
    const result = await client.pipeline.listRunPage({ status: "failed", documentId: "doc-1", limit: 10, cursor: "c1" });
    expect(call(fetcher)).toMatchObject({ method: "GET", path: "/v2/runs", query: { workspace_id: "workspace-1", status: "failed", document_id: "doc-1", limit: "10", cursor: "c1" } });
    expect(result.nextCursor).toBe("c2");
    expect(result.items[0]).toMatchObject({ id: "run-9", status: "failed", documentId: "doc-1", format: "html", policy: "draft", percent: 40, stage: "build" });
  });

  it("omits empty filters", async () => {
    const { client, fetcher } = setup(() => json({ items: [] }));
    await client.pipeline.listRunPage({});
    expect(call(fetcher).query).toEqual({ workspace_id: "workspace-1" });
  });

  it("normalizes a server error on the pipeline routes", async () => {
    const { client } = setup(() => json({ error: { code: "unknown_pipeline", message: "Unknown pipeline: nope" } }, { status: 400, headers: { "x-request-id": "req-7", "content-type": "application/json" } }));
    const error = await client.pipeline.planPipeline("doc-1", { pipelineId: "nope" }).catch(e => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 400, code: "unknown_pipeline", message: "Unknown pipeline: nope", requestId: "req-7" });
  });

  it("turns a raw run into a summary without raw JSON", () => {
    expect(toRunRecord({ id: "r", status: "queued", created_at: "t", payload: {} })).toMatchObject({ id: "r", status: "queued", createdAt: "t" });
  });
});

describe("streamProgress terminal event", () => {
  beforeEach(() => { localStorage.setItem("docs.review.workspace", "workspace-1"); });

  it("stops at the terminal event without reconnecting and reports it", async () => {
    const { client, fetcher } = setup(() => sse(
      ": keepalive\n\n",
      "id: r1\nevent: progress\ndata: {\"type\":\"build\",\"progress\":50,\"run\":{\"id\":\"r1\",\"status\":\"running\"}}\n\n",
      "id: r1\nevent: terminal\ndata: {\"run\":{\"id\":\"r1\",\"status\":\"succeeded\"}}\n\n",
    ));
    const events: Array<{ type: string }> = [];
    await client.streamProgress("r1", event => events.push(event));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(events.map(e => e.type)).toEqual(["build", "terminal"]);
  });

  it("sends the Bearer token on the progress stream like every other request", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => sse("event: terminal\ndata: {\"run\":{\"id\":\"r1\",\"status\":\"succeeded\"}}\n\n"));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", accessToken: "token-123", fetch: fetcher });
    await client.streamProgress("r1", () => {});
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ headers: { Accept: "text/event-stream", Authorization: "Bearer token-123" } });
  });

  it("recognises a terminal event even when the run status is not in the known list", async () => {
    const { client, fetcher } = setup(() => sse("event: terminal\ndata: {\"run\":{\"id\":\"r1\",\"status\":\"timed_out\"}}\n\n"));
    await client.streamProgress("r1", () => {});
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
