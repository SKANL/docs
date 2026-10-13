// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/errors";
import { yieldSse } from "../api/domains/pipeline";
import { ReviewApiClient } from "../api/client";

const jsonResponse = (body: unknown, init: ResponseInit = {}) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" }, ...init });

describe("ReviewApiClient", () => {
  beforeEach(() => { localStorage.setItem("docs.review.workspace", "workspace-1"); });
  it("downloads a translation as a Blob with the Bearer header", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response("%PDF", { status: 200, headers: { "content-type": "application/pdf" } }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", accessToken: "token-123", fetch: fetcher });
    const blob = await client.tools.downloadTranslation("artifacts/translations/a b.es.pdf");
    expect(blob.size).toBe(4);
    expect(fetcher.mock.calls[0]?.[0].toString()).toBe("https://review.test/v2/translations/output?path=artifacts%2Ftranslations%2Fa+b.es.pdf&workspace_id=workspace-1");
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ headers: { Authorization: "Bearer token-123" } });
  });

  it("surfaces a failed translation download as an ApiError", async () => {
    const fetcher = vi.fn(async () => jsonResponse({ error: { code: "output_not_found", message: "gone" } }, { status: 404 }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });
    await expect(client.tools.downloadTranslation("artifacts/translations/x.pdf")).rejects.toMatchObject({ code: "output_not_found", status: 404 });
  });

  it("appends /v2 to a bare origin and keeps an explicit /v2", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL) => jsonResponse({ items: [] }));
    await new ReviewApiClient({ baseUrl: "https://review.test", fetch: fetcher }).pipeline.listRunPage();
    await new ReviewApiClient({ baseUrl: "https://review.test/v2/", fetch: fetcher }).pipeline.listRunPage();
    expect(fetcher.mock.calls.map(call => call[0].toString())).toEqual(["https://review.test/v2/runs?workspace_id=workspace-1", "https://review.test/v2/runs?workspace_id=workspace-1"]);
  });

  it("bootstraps an explicit local workspace before scoped content requests", async () => {
    localStorage.clear();
    const fetcher = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(input.toString());
      return Promise.resolve(url.pathname.endsWith("/workspaces")
        ? jsonResponse({ items: [{ id: "workspace-a", name: "A", root: "/a" }] })
        : jsonResponse({ items: [] }));
    });
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });

    await client.pipeline.listRunPage();

    expect(fetcher.mock.calls.map(call => call[0].toString())).toEqual([
      "https://review.test/v2/workspaces",
      "https://review.test/v2/runs?workspace_id=workspace-a",
    ]);
    expect(localStorage.getItem("docs.review.workspace")).toBe("workspace-a");
  });

  it("keeps workspace selection local and creates a workspace by name only", async () => {
    localStorage.clear();
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
      return jsonResponse({ id: "workspace-b", name: "B", root: "/managed/b" });
    });
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });

    await client.workspaces.createWorkspace({ name: "B" });

    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({ name: "B" });
    expect(fetcher.mock.calls.map(call => new URL(call[0].toString()).pathname)).toEqual([
      "/v2/workspaces",
      "/v2/workspaces/workspace-b/use",
    ]);
    expect(localStorage.getItem("docs.review.workspace")).toBe("workspace-b");
  });

  it("returns the persisted workspace first when the server lists another workspace first", async () => {
    localStorage.setItem("docs.review.workspace", "workspace-b");
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ items: [
      { id: "workspace-a", name: "A", root: "/a" },
      { id: "workspace-b", name: "B", root: "/b" },
    ] }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });

    const result = await client.workspaces.listWorkspaces();

    expect(result.map(item => item.id)).toEqual(["workspace-b", "workspace-a"]);
  });

  it("uses canonical workspace and document lifecycle routes with explicit workspace scope", async () => {
    const workspace = { id: "workspace-1", name: "Research", root: "/managed/research" };
    const summary = { id: "field-notes", title: "Field notes", template: "documento-generico", active: true };
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(input.toString());
      calls.push({ url, init });
      if (url.pathname === "/v2/workspaces" && init?.method === undefined) return jsonResponse({ items: [workspace] });
      if (url.pathname.endsWith("/use") && url.pathname.startsWith("/v2/workspaces/")) return jsonResponse(workspace);
      if (url.pathname.endsWith("/status") && url.pathname.startsWith("/v2/workspaces/")) return jsonResponse({ workspace, active: true });
      if (url.pathname === "/v2/documents") return jsonResponse({ items: [summary] });
      if (url.pathname === "/v2/current-document") return jsonResponse({ current_document_id: summary.id, document: summary });
      if (url.pathname.endsWith("/use") && url.pathname.startsWith("/v2/documents/")) return jsonResponse(summary);
      if (url.pathname === "/v2/documents/field-notes" && init?.method === "PATCH") return jsonResponse({ ...summary, id: "field-notes-renamed" });
      if (url.pathname === "/v2/documents/field-notes" && init?.method === "DELETE") return jsonResponse({ deleted: summary.id, current_document_id: null });
      if (url.pathname.endsWith("/status") && url.pathname.startsWith("/v2/documents/")) return jsonResponse({ document_id: summary.id, succeeded: true });
      return jsonResponse({});
    });
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });

    await client.workspaces.listWorkspaces();
    await client.workspaces.selectWorkspace(workspace.id);
    await client.workspaces.getWorkspaceStatus(workspace.id);
    await client.workspaces.listDocuments(workspace.id);
    await client.workspaces.getCurrentDocument(workspace.id);
    await client.workspaces.useDocument(summary.id, workspace.id);
    await client.workspaces.renameDocument(summary.id, "field-notes-renamed", workspace.id);
    await client.workspaces.deleteDocument(summary.id, workspace.id);
    await client.workspaces.getDocumentStatus(summary.id, workspace.id);

    expect(calls.map(({ url }) => `${url.pathname}${url.search}`)).toEqual([
      "/v2/workspaces",
      "/v2/workspaces/workspace-1/use",
      "/v2/workspaces/workspace-1/status",
      "/v2/documents?workspace_id=workspace-1",
      "/v2/current-document?workspace_id=workspace-1",
      "/v2/documents/field-notes/use?workspace_id=workspace-1",
      "/v2/documents/field-notes?workspace_id=workspace-1",
      "/v2/documents/field-notes?workspace_id=workspace-1",
      "/v2/documents/field-notes/status?workspace_id=workspace-1",
    ]);
    expect(JSON.parse(String(calls[6]?.init?.body))).toEqual({ new_id: "field-notes-renamed" });
    expect(calls[7]?.init?.method).toBe("DELETE");
    expect(localStorage.getItem("docs.review.workspace")).toBe(workspace.id);
  });
  it("retries transient startup connection failures before surfacing an error", async () => {
    let attempts = 0;
    const client = new ReviewApiClient({
      baseUrl: "http://review.test/v2",
      fetch: async () => {
        attempts += 1;
        if (attempts < 3) throw new TypeError("Failed to fetch");
        return jsonResponse({ items: [{ id: "run-after-startup" }] });
      },
    });

    await expect(client.pipeline.listRunPage()).resolves.toMatchObject({ items: [{ id: "run-after-startup" }] });
    expect(attempts).toBe(3);
  });
  it("builds typed paginated /v2 requests", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ items: [{ id: "run-1" }], next_cursor: "next", total: 4 }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });
    await expect(client.pipeline.listRunPage({ cursor: "a b", limit: 2 })).resolves.toMatchObject({ items: [{ id: "run-1" }], nextCursor: "next" });
    expect(fetcher.mock.calls[0][0].toString()).toBe("https://review.test/v2/runs?limit=2&cursor=a+b&workspace_id=workspace-1");
  });

  it("serializes semantic graph domain queries with an optional id", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });

    await client.review.getGraphQuery("findings_affected_by_revision", "rev 1");

    expect(fetcher.mock.calls[0][0].toString()).toBe("https://review.test/v2/graph?query=findings_affected_by_revision&id=rev+1&workspace_id=workspace-1");
  });

  it("maps the production runtime run envelope to a run record", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ items: [{
      schema: "docs.runtime/v1",
      id: "run-real",
      status: "succeeded",
      created_at: "2026-09-21T12:00:00Z",
      payload: {
        document_id: "doc-real",
        template: "technical-report-srs",
        started_at: "2026-09-21T12:00:01Z",
        duration_ms: 1250,
        artifact_count: 3,
        findings: 2,
        progress: { percent: 100 },
        report: { execution: { results: [{ artifacts: ["a", "b"], warnings: ["w"], errors: [] }] } },
      },
    }]}));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });

    await expect(client.pipeline.listRunPage()).resolves.toMatchObject({ items: [{
      id: "run-real",
      documentId: "doc-real",
      status: "succeeded",
      createdAt: "2026-09-21T12:00:00Z",
      percent: 100,
    }] });
  });

  it("attaches a configured bearer token without replacing request headers", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", accessToken: "token-123", fetch: fetcher });

    await client.pipeline.listRunPage();

    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ headers: { Accept: "application/json", Authorization: "Bearer token-123" } });
  });

  it("passes the selected output format to document actions", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ id: "run-pdf" }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });
    await client.pipeline.documentAction("doc-1", "build", "workspace-1", "pdf");
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toMatchObject({ workspace_id: "workspace-1", format: "pdf" });
  });

  it("scopes graph domain queries to the selected workspace", async () => {
    const fetcher = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(input.toString());
      return Promise.resolve(url.pathname.endsWith("/workspaces")
        ? jsonResponse({ items: [{ id: "workspace-2", name: "Workspace 2", root: "C:/workspace-2" }] })
        : jsonResponse({ items: [] }));
    });
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });
    await client.workspaces.listWorkspaces();
    await client.workspaces.selectWorkspace("workspace-2");
    await client.review.getGraphQuery("unused_references");
    const lastCall = fetcher.mock.calls[fetcher.mock.calls.length - 1];
    expect(lastCall?.[0].toString()).toBe("https://review.test/v2/graph?query=unused_references&workspace_id=workspace-2");
  });

  it("normalizes backend graph nodes and edges without changing the UI shape", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ nodes: [{ id: "claim-1", kind: "claim", label: "Claim", confidence: { score: 0.75 } }], edges: [{ source: "source-1", target: "claim-1", relation: "supports" }] }));
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });
    await expect(client.review.getGraph()).resolves.toMatchObject({ nodes: [{ id: "claim-1", type: "claim", confidence: 0.75 }], edges: [{ from: "source-1", to: "claim-1" }] });
  });

  it("normalizes structured API errors", async () => {
    const client = new ReviewApiClient({ fetch: vi.fn().mockResolvedValue(jsonResponse({ code: "invalid_run", message: "Run not found", details: { id: "x" } }, { status: 404, statusText: "Not Found", headers: { "x-request-id": "req-1" } })) });
    await expect(client.review.getRunEvidence("x")).rejects.toMatchObject({ name: "ApiError", status: 404, code: "invalid_run", requestId: "req-1", details: { id: "x" } });
  });

  it("aborts requests after the configured timeout", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_, reject) => init?.signal?.addEventListener("abort", () => reject(init.signal?.reason))));
    const promise = new ReviewApiClient({ fetch: fetcher, timeoutMs: 25 }).pipeline.listRunPage();
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
    const client = new ReviewApiClient({ baseUrl: "https://review.test/v2" });
    expect(client.previewUrl("/preview/page-1.png")).toBe("https://review.test/preview/page-1.png");
    expect(() => client.previewUrl("https://evil.test/page.png")).toThrow(TypeError);
    expect(() => client.previewUrl("data:text/html,boom")).toThrow(TypeError);
    expect(new ReviewApiClient({ baseUrl: "https://review.test/v2", allowedPreviewOrigins: ["https://cdn.test"] }).previewUrl("https://cdn.test/page.png")).toBe("https://cdn.test/page.png");
  });
});

it("exports a stable normalized error type", () => expect(new ApiError("x", 400).code).toBe("api_error"));
