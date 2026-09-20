import { describe, expect, it, vi } from "vitest";
import { ApiError, ReviewApiClient, yieldSse } from "../api/client";

const jsonResponse = (body: unknown, init: ResponseInit = {}) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" }, ...init });

describe("ReviewApiClient", () => {
  it("builds typed paginated /v1 requests", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ items: [{ id: "run-1" }], next_cursor: "next", total: 4 }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v1", fetch: fetcher });
    await expect(client.listRuns({ cursor: "a b", limit: 2 })).resolves.toEqual({ items: [{ id: "run-1" }], nextCursor: "next", total: 4 });
    expect(fetcher.mock.calls[0][0].toString()).toBe("https://review.test/v1/runs?cursor=a+b&limit=2");
  });

  it("serializes semantic graph domain queries with an optional id", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v1", fetch: fetcher });

    await client.getGraphQuery("findings_affected_by_revision", "rev 1");

    expect(fetcher.mock.calls[0][0].toString()).toBe("https://review.test/v1/graph?query=findings_affected_by_revision&id=rev+1");
  });

  it("normalizes backend graph nodes and edges without changing the UI shape", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ nodes: [{ id: "claim-1", kind: "claim", label: "Claim", confidence: { score: 0.75 } }], edges: [{ source: "source-1", target: "claim-1", relation: "supports" }] }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v1", fetch: fetcher });
    await expect(client.getGraph()).resolves.toMatchObject({ nodes: [{ id: "claim-1", type: "claim", confidence: 0.75 }], edges: [{ from: "source-1", to: "claim-1" }] });
  });

  it("normalizes structured API errors", async () => {
    const client = new ReviewApiClient({ fetch: vi.fn().mockResolvedValue(jsonResponse({ code: "invalid_run", message: "Run not found", details: { id: "x" } }, { status: 404, statusText: "Not Found", headers: { "x-request-id": "req-1" } })) });
    await expect(client.getPassport("x")).rejects.toMatchObject({ name: "ApiError", status: 404, code: "invalid_run", requestId: "req-1", details: { id: "x" } });
  });

  it("aborts requests after the configured timeout", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_, reject) => init?.signal?.addEventListener("abort", () => reject(init.signal?.reason))));
    const promise = new ReviewApiClient({ fetch: fetcher, timeoutMs: 25 }).listRuns();
    const rejected = expect(promise).rejects.toMatchObject({ name: "TimeoutError" });
    await vi.advanceTimersByTimeAsync(25);
    await rejected;
    vi.useRealTimers();
  });

  it("parses SSE progress records without injecting markup", async () => {
    const seen: unknown[] = [];
    const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new TextEncoder().encode('data: {"type":"progress","progress":0.5}\n\n')); controller.enqueue(new TextEncoder().encode('data: {"type":"message","message":"<b>safe</b>"}\n\n')); controller.close(); } });
    await yieldSse(stream, (event) => seen.push(event));
    expect(seen).toEqual([{ type: "progress", progress: 0.5 }, { type: "message", message: "<b>safe</b>" }]);
  });

  it("allows same-origin previews only unless explicitly configured", () => {
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v1" });
    expect(client.previewUrl("/preview/page-1.png")).toBe("https://review.test/preview/page-1.png");
    expect(() => client.previewUrl("https://evil.test/page.png")).toThrow(TypeError);
    expect(() => client.previewUrl("data:text/html,boom")).toThrow(TypeError);
    expect(new ReviewApiClient({ baseUrl: "https://review.test/v1", allowedPreviewOrigins: ["https://cdn.test"] }).previewUrl("https://cdn.test/page.png")).toBe("https://cdn.test/page.png");
  });
});

it("exports a stable normalized error type", () => expect(new ApiError("x", 400).code).toBe("api_error"));
