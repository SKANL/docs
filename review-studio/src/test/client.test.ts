import { describe, expect, it, vi } from "vitest";
import { ApiError, ReviewApiClient, yieldSse } from "../api/client";

const jsonResponse = (body: unknown, init: ResponseInit = {}) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" }, ...init });

describe("ReviewApiClient", () => {
  it("retries transient startup connection failures before surfacing an error", async () => {
    let attempts = 0;
    const client = new ReviewApiClient({
      baseUrl: "http://review.test/v1",
      fetch: async () => {
        attempts += 1;
        if (attempts < 3) throw new TypeError("Failed to fetch");
        return jsonResponse({ items: [{ id: "run-after-startup" }] });
      },
    });

    await expect(client.listRuns()).resolves.toMatchObject({ items: [{ id: "run-after-startup" }] });
    expect(attempts).toBe(3);
  });
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

  it("attaches a configured bearer token without replacing request headers", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v1", accessToken: "token-123", fetch: fetcher });

    await client.listRuns();

    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ headers: { Accept: "application/json", Authorization: "Bearer token-123" } });
  });

  it("passes the selected output format to document actions", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ id: "run-pdf" }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v1", fetch: fetcher });
    await client.documentAction("doc-1", "build", "workspace-1", "pdf");
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toMatchObject({ workspace_id: "workspace-1", format: "pdf" });
  });

  it("scopes graph domain queries to the selected workspace", async () => {
    const fetcher = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const path = new URL(input.toString()).pathname;
      return Promise.resolve(path.endsWith("/select")
        ? jsonResponse({ id: "workspace-2", name: "Workspace 2", root: "C:/workspace-2" })
        : jsonResponse({ items: [] }));
    });
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v1", fetch: fetcher });
    await client.selectWorkspace("workspace-2");
    await client.getGraphQuery("unused_references");
    const lastCall = fetcher.mock.calls[fetcher.mock.calls.length - 1];
    expect(lastCall?.[0].toString()).toBe("https://review.test/v1/graph?query=unused_references&workspace_id=workspace-2");
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
