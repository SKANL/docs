// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReviewApiClient } from "../api/client";
import { createReviewApi } from "../api/factory";

const jsonResponse = (body: unknown, init: ResponseInit = {}) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" }, ...init });

function setup(body: unknown = {}, init: ResponseInit = {}) {
  const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse(body, init));
  const client = new ReviewApiClient({ baseUrl: "https://review.test/v2", fetch: fetcher });
  const call = () => {
    const [input, init] = fetcher.mock.calls[0]!;
    const url = new URL(input.toString());
    return { path: url.pathname, query: Object.fromEntries(url.searchParams), method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined };
  };
  return { client, call };
}

describe("authoring client", () => {
  beforeEach(() => { localStorage.setItem("docs.review.workspace", "ws-1"); });

  it("lists assets with the workspace scope and optional kind", async () => {
    const { client, call } = setup({ document_id: "d 1", kind: "docx", items: [{ name: "portada" }] });
    await expect(client.authoring.listAssets("d 1", "docx")).resolves.toMatchObject({ items: [{ name: "portada" }] });
    expect(call()).toEqual({ path: "/v2/documents/d%201/assets", query: { kind: "docx", workspace_id: "ws-1" }, method: "GET", body: undefined });
  });

  it("adds an asset as snake_case JSON and omits an empty name", async () => {
    const { client, call } = setup({ document_id: "d", name: "x", path: "assets/x.docx" });
    await client.authoring.addAsset("d", { filename: "x.docx", contentBase64: "eA==" });
    expect(call()).toMatchObject({ path: "/v2/documents/d/assets", method: "POST", body: { filename: "x.docx", content_base64: "eA==" }, query: { workspace_id: "ws-1" } });
    expect(call().body).not.toHaveProperty("name");
  });

  it("removes an asset by encoded name", async () => {
    const { client, call } = setup({ document_id: "d", removed: "a b" });
    await client.authoring.removeAsset("d", "a b");
    expect(call()).toMatchObject({ path: "/v2/documents/d/assets/a%20b", method: "DELETE" });
  });

  it("ingests uploads and returns the typed result", async () => {
    const { client, call } = setup({ document_id: "d", succeeded: true, artifacts: [], uploaded: [], stages: [] });
    await expect(client.authoring.ingestSources("d", [{ filename: "n.md", content_base64: "eA==" }])).resolves.toMatchObject({ succeeded: true });
    expect(call()).toMatchObject({ path: "/v2/documents/d/ingest", method: "POST", body: { files: [{ filename: "n.md", content_base64: "eA==" }] } });
  });

  it("reads and confirms classification", async () => {
    const read = setup({ document_id: "d", items: [] });
    await read.client.authoring.getClassificationQueue("d");
    expect(read.call()).toMatchObject({ path: "/v2/documents/d/classification", method: "GET" });
    const confirm = setup({ document_id: "d", items: [] });
    await confirm.client.authoring.confirmClassification("d", { relative_path: "a/x.md", confirmed_role: "normative" });
    expect(confirm.call()).toMatchObject({ method: "POST", body: { relative_path: "a/x.md", confirmed_role: "normative" } });
  });

  it("elicits, ingests, shows and removes context topics", async () => {
    const elicit = setup({ document_id: "d", path: "context/_requests.md", markdown: "" });
    await elicit.client.authoring.elicitContext("d", "tema");
    expect(elicit.call()).toMatchObject({ path: "/v2/documents/d/context/requests", method: "POST", body: { topic: "tema" } });
    const ingest = setup({ document_id: "d", topics: ["tema"] });
    await ingest.client.authoring.ingestContext("d");
    expect(ingest.call()).toMatchObject({ path: "/v2/documents/d/context/ingest", method: "POST", body: {} });
    const show = setup({ document_id: "d", topic: "tema", content: "x" });
    await show.client.authoring.showContextTopic("d", "tema");
    expect(show.call()).toMatchObject({ path: "/v2/documents/d/context/tema", method: "GET" });
    const remove = setup({ document_id: "d", removed: "tema" });
    await remove.client.authoring.removeContextTopic("d", "tema");
    expect(remove.call()).toMatchObject({ path: "/v2/documents/d/context/tema", method: "DELETE" });
  });

  it("normalizes the server error envelope into ApiError", async () => {
    const { client } = setup({ error: { code: "invalid_filename", message: "Invalid name", details: {} } }, { status: 400, statusText: "Bad Request" });
    await expect(client.authoring.addAsset("d", { filename: "../x", contentBase64: "eA==" })).rejects.toMatchObject({ name: "ApiError", status: 400, code: "invalid_filename", message: "Invalid name" });
  });

  it("is exposed on the ReviewApi produced by the factory", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL) => jsonResponse({ document_id: "d", kind: "docx", items: [] }));
    const api = createReviewApi({ apiBaseUrl: "https://review.test/v2", fetch: fetcher });
    await api.listAssets?.("d");
    expect(new URL(String(fetcher.mock.calls[0]![0])).pathname).toBe("/v2/documents/d/assets");
    expect(typeof api.confirmClassification).toBe("function");
  });

  it("sends the workspace scope on classification reads and confirmations", async () => {
    const read = setup({ document_id: "d", items: [] });
    await read.client.getDocumentClassification("d");
    expect(read.call()).toMatchObject({ method: "GET", query: { workspace_id: "ws-1" } });
    const confirm = setup({ document_id: "d", items: [] });
    await confirm.client.confirmDocumentClassification("d", { relative_path: "a/x.md", confirmed_role: "evidence" });
    expect(confirm.call()).toMatchObject({ method: "POST", query: { workspace_id: "ws-1" } });
  });

  it("builds a section and packs context", async () => {
    const build = setup({ document_id: "d", section_id: "intro", path: "sections/020-intro.md", proposal: false });
    await expect(build.client.authoring.buildSection("d", "in tro")).resolves.toMatchObject({ proposal: false });
    expect(build.call()).toMatchObject({ path: "/v2/documents/d/sections/in%20tro/build", method: "POST", body: {} });
    const pack = setup({ document_id: "d", target: "all", paths: ["a"] });
    await expect(pack.client.authoring.packContext("d", "all")).resolves.toMatchObject({ paths: ["a"] });
    expect(pack.call()).toMatchObject({ path: "/v2/documents/d/context-pack", method: "POST", body: { target: "all" } });
  });

  it("reviews a section and a document with structured findings", async () => {
    const finding = { severity: "error", message: "m", code: "c", dimension: "editorial" };
    const section = setup({ document_id: "d", section_id: "intro", passed: false, findings: [finding] });
    const reviewed = await section.client.authoring.reviewSection("d", "intro", { strict: true });
    expect(reviewed.findings[0]?.code).toBe("c");
    expect(section.call()).toMatchObject({ path: "/v2/documents/d/sections/intro/review", method: "POST", body: { strict: true } });
    const document = setup({ document_id: "d", section_id: null, passed: true, findings: [] });
    await document.client.authoring.reviewDocument("d", { dimensions: ["structural"] });
    expect(document.call()).toMatchObject({ path: "/v2/documents/d/review", method: "POST", body: { dimensions: ["structural"] } });
  });

  it("stamps a section with the actor and revises a document", async () => {
    const stamp = setup({ document_id: "d", section_id: "intro", path: "p", authored_by: "ada", model: "m", stamped_at: "t" });
    await stamp.client.authoring.stampSection("d", "intro", { by: "ada", model: "m" });
    expect(stamp.call()).toMatchObject({ path: "/v2/documents/d/sections/intro/stamp", method: "POST", body: { by: "ada", model: "m" } });
    const revise = setup({ target_id: "intro", diff: "", summary: "", changed_sections: ["intro"], diff_path: "sections/_revisions/x.diff" });
    await expect(revise.client.authoring.reviseDocument("d", { target_id: "intro", new_body: "x", request: "r" })).resolves.toMatchObject({ diff_path: "sections/_revisions/x.diff" });
    expect(revise.call()).toMatchObject({ path: "/v2/documents/d/revisions", method: "POST", body: { target_id: "intro", new_body: "x", request: "r" } });
  });
});
