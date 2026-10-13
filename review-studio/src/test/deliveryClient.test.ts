// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/errors";
import { ReviewApiClient } from "../api/client";

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

describe("delivery client", () => {
  beforeEach(() => { localStorage.setItem("docs.review.workspace", "workspace-1"); });

  it("packages a document and sends only the chosen fields", async () => {
    const result = { document_id: "doc 1", run_id: "run-1", source: "s", destination: "d.zip", sha256: "a".repeat(64), size_bytes: 10 };
    const { client, fetcher } = setup(() => json(result));
    await expect(client.delivery.packageDocument("doc 1", { runId: "run-1" })).resolves.toEqual(result);
    expect(call(fetcher)).toMatchObject({ method: "POST", path: "/v2/documents/doc%201/package", query: { workspace_id: "workspace-1" }, body: { run_id: "run-1" } });
  });

  it("publishes to a relative destination with the chosen policy", async () => {
    const { client, fetcher } = setup(() => json({ id: "pub-1" }, { status: 201 }));
    await client.delivery.publishDocument("doc-1", { destination: "final.html", policy: "strict", format: "html" });
    expect(call(fetcher)).toMatchObject({ method: "POST", path: "/v2/documents/doc-1/publications", query: { workspace_id: "workspace-1" }, body: { destination: "final.html", policy: "strict", format: "html" } });
  });

  it("keeps the server code and message on a policy denial", async () => {
    const { client } = setup(() => json({ error: { code: "publish_policy_denied", message: "draft artifacts cannot be released" } }, { status: 422 }));
    const error = await client.delivery.publishDocument("doc-1", { destination: "x.html", policy: "draft" }).catch(e => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: "publish_policy_denied", message: "draft artifacts cannot be released" });
  });

  it("reads the publication history into records", async () => {
    const raw = { id: "pub-1", document_id: "doc-1", run_id: "run-3", destination: "d.html", artifact_sha256: "e".repeat(64), published_at: "t", approver: "local", status: "passed", policy: "release", warnings: ["w"] };
    const { client, fetcher } = setup(() => json({ items: [raw] }));
    const records = await client.delivery.listPublicationHistory();
    expect(call(fetcher)).toMatchObject({ method: "GET", path: "/v2/publications", query: { workspace_id: "workspace-1" } });
    expect(records[0]).toMatchObject({ id: "pub-1", documentId: "doc-1", runId: "run-3", destination: "d.html", policy: "release", warnings: ["w"], approver: "local" });
  });
});
