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

describe("templates client", () => {
  beforeEach(() => { localStorage.setItem("docs.review.workspace", "workspace-1"); });

  it("reads the built-in catalogue", async () => {
    const { client, fetcher } = setup(() => json({ items: [{ name: "report", installed: true }] }));
    await expect(client.templates.listTemplateCatalog()).resolves.toEqual([{ name: "report", installed: true }]);
    expect(call(fetcher)).toMatchObject({ method: "GET", path: "/v2/template-catalog", query: { workspace_id: "workspace-1" } });
  });

  it("shows, installs, creates and validates through the template routes", async () => {
    const { client, fetcher } = setup(() => json({ name: "report", path: "templates/report.json", passed: true, issues: [], template: {} }, { status: 200 }));
    await client.templates.showTemplate("my report");
    await client.templates.installBuiltinTemplate("report", { force: true });
    await client.templates.createTemplate("fresh");
    await client.templates.validateTemplate("report", { sections: [] });
    await client.templates.validateTemplate("report");
    expect(call(fetcher, 0)).toMatchObject({ method: "GET", path: "/v2/templates/my%20report" });
    expect(call(fetcher, 1)).toMatchObject({ method: "POST", path: "/v2/templates/report/use", body: { force: true } });
    expect(call(fetcher, 2)).toMatchObject({ method: "POST", path: "/v2/templates", body: { name: "fresh" } });
    expect(call(fetcher, 3)).toMatchObject({ method: "POST", path: "/v2/templates/report/validate", body: { template: { sections: [] } } });
    expect(call(fetcher, 4).body).toEqual({});
  });

  it("keeps the template_exists code so the UI can ask before overwriting", async () => {
    const { client } = setup(() => json({ error: { code: "template_exists", message: "Template already exists" } }, { status: 409 }));
    const error = await client.templates.installBuiltinTemplate("report", { force: false }).catch(e => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "template_exists" });
  });
});

describe("tools client", () => {
  beforeEach(() => { localStorage.setItem("docs.review.workspace", "workspace-1"); });

  it("reads diagnostics for a document and explains an issue code", async () => {
    const { client, fetcher } = setup(() => json({ checks: [] }));
    await client.tools.getDiagnostics({ documentId: "doc 1", strict: true });
    await client.tools.explainIssueCode("QA.001");
    expect(call(fetcher, 0)).toMatchObject({ method: "GET", path: "/v2/diagnostics", query: { workspace_id: "workspace-1", document_id: "doc 1", strict: "true" } });
    expect(call(fetcher, 1)).toMatchObject({ method: "GET", path: "/v2/issue-codes/QA.001" });
  });

  it("runs file tools with only the chosen repo root", async () => {
    const { client, fetcher } = setup(() => json({ document_id: "doc-1", path: "x" }));
    await client.tools.runFileTool("collect-issues", "doc-1", { repoRoot: "repo" });
    await client.tools.runFileTool("build-ledger", "doc-1");
    expect(call(fetcher, 0)).toMatchObject({ method: "POST", path: "/v2/documents/doc-1/collect-issues", body: { repo_root: "repo" } });
    expect(call(fetcher, 1)).toMatchObject({ method: "POST", path: "/v2/documents/doc-1/build-ledger", body: {} });
  });

  it("posts rules review, docx build and format audit", async () => {
    const { client, fetcher } = setup(() => json({}));
    await client.tools.reviewRules("doc-1", { strict: true });
    await client.tools.buildDocx("doc-1", { output: "out/a.docx" });
    await client.tools.auditDocxFormat("doc-1", { strict: true });
    expect(call(fetcher, 0)).toMatchObject({ path: "/v2/documents/doc-1/review-rules", body: { strict: true } });
    expect(call(fetcher, 1)).toMatchObject({ path: "/v2/documents/doc-1/build-docx", body: { output: "out/a.docx" } });
    expect(call(fetcher, 2)).toMatchObject({ path: "/v2/documents/doc-1/format-audit-docx", body: { strict: true } });
  });

  it("translates with snake_case fields and keeps output_exists", async () => {
    const { client, fetcher } = setup(() => json({ error: { code: "output_exists", message: "The output already exists" } }, { status: 409 }));
    const error = await client.tools.translatePdf({ artifactId: "a1", to: "es", sourceLang: "en", overwrite: false }).catch(e => e);
    expect(call(fetcher)).toMatchObject({ method: "POST", path: "/v2/translations", body: { artifact_id: "a1", to: "es", source_lang: "en", overwrite: false } });
    expect(error).toMatchObject({ status: 409, code: "output_exists" });
  });

  it("reads the document summary and imports a source file", async () => {
    const { client, fetcher } = setup(() => json({ document_id: "doc-1", summary: { a: 1 } }));
    await client.tools.getDocumentSummary("doc-1");
    await client.tools.importSourceFile("doc-1", { filename: "a.md", content_base64: "QQ==" });
    expect(call(fetcher, 0)).toMatchObject({ method: "GET", path: "/v2/documents/doc-1/summary" });
    expect(call(fetcher, 1)).toMatchObject({ method: "POST", path: "/v2/documents/doc-1/imports", body: { filename: "a.md", content_base64: "QQ==" } });
  });
});
