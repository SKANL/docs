// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/errors";
import { ok, openAt, toolsApi, toolsCatalog } from "./toolsHarness";

afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); });

const card = async (title: string) => {
  const region = await screen.findByRole("region", { name: title });
  await userEvent.click(within(region).getByRole("button", { name: `Open ${title}` }));
  return region;
};

describe("tools area", () => {
  it("keeps every tool collapsed until it is opened (progressive disclosure)", async () => {
    openAt("/tools", toolsApi());
    const region = await screen.findByRole("region", { name: "Collect issues" });
    expect(screen.queryByRole("button", { name: "Run Collect issues" })).toBeNull();
    const open = within(region).getByRole("button", { name: "Open Collect issues" });
    expect(open.getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(open);
    expect(within(region).getByRole("button", { name: "Run Collect issues" })).toBeTruthy();
    expect(open.getAttribute("aria-expanded")).toBe("true");
  });

  it("lists Tools as a secondary sidebar entry (under Advanced) and keeps specialist controls out of authoring", async () => {
    localStorage.setItem("review-studio.advanced", "true");
    openAt("/authoring/sources", toolsApi());
    const secondary = await screen.findByRole("navigation", { name: "Specialist tools" });
    expect(within(secondary).getByRole("link", { name: "Tools" }).getAttribute("href")).toContain("/tools");
    expect(within(screen.getByRole("navigation", { name: "Task areas" })).queryByRole("link", { name: "Tools" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Open Collect|Open Build|Open Translate/ })).toBeNull();
  });

  it("collects sources for the current document and shows the written path", async () => {
    const runFileTool = vi.fn(async () => ok("documents/doc-1/sources.json"));
    openAt("/tools", toolsApi({ runFileTool }));
    const region = await card("Collect sources");
    await userEvent.click(within(region).getByRole("button", { name: "Run Collect sources" }));
    await waitFor(() => expect(runFileTool).toHaveBeenCalledWith("collect-sources", "doc-1", {}));
    expect((await within(region).findByRole("status")).textContent).toContain("documents/doc-1/sources.json");
  });

  it("shows the server error when a repository root is refused", async () => {
    const runFileTool = vi.fn(async () => { throw new ApiError("repo_root must be the workspace or the configured evidence root", 400, "repo_root_not_permitted"); });
    openAt("/tools", toolsApi({ runFileTool }));
    const region = await card("Collect issues");
    await userEvent.type(within(region).getByRole("textbox", { name: "Repository root (optional)" }), "C:/elsewhere");
    await userEvent.click(within(region).getByRole("button", { name: "Run Collect issues" }));
    expect((await within(region).findByRole("alert")).textContent).toContain("repo_root must be the workspace");
    expect(runFileTool).toHaveBeenCalledWith("collect-issues", "doc-1", { repoRoot: "C:/elsewhere" });
  });

  it("collects code evidence and reports a degraded tool instead of success", async () => {
    const runFileTool = vi.fn(async () => ({ document_id: "doc-1", path: null, degraded: true, message: "gh is not installed" }));
    openAt("/tools", toolsApi({ runFileTool }));
    const region = await card("Collect code evidence");
    await userEvent.click(within(region).getByRole("button", { name: "Run Collect code evidence" }));
    const alert = await within(region).findByRole("alert");
    expect(alert.textContent).toContain("gh is not installed");
    expect(within(region).queryByRole("status")).toBeNull();
  });

  it("builds the evidence rules and the fact ledger", async () => {
    const runFileTool = vi.fn(async (tool: string) => ok(`artifacts/${tool}.json`));
    openAt("/tools", toolsApi({ runFileTool }));
    const rules = await card("Build rules");
    await userEvent.click(within(rules).getByRole("button", { name: "Run Build rules" }));
    await waitFor(() => expect(runFileTool).toHaveBeenCalledWith("build-rules", "doc-1", {}));
    const ledger = await card("Build ledger");
    await userEvent.click(within(ledger).getByRole("button", { name: "Run Build ledger" }));
    await waitFor(() => expect(runFileTool).toHaveBeenCalledWith("build-ledger", "doc-1", {}));
    expect((await within(ledger).findByRole("status")).textContent).toContain("artifacts/build-ledger.json");
  });

  it("reviews rules with a strict toggle and lists the issues", async () => {
    const reviewRules = vi.fn(async () => ({ document_id: "doc-1", strict: true, passed: false, issues: [{ code: "rules.stale", message: "Rule R1 has no evidence" }] }));
    openAt("/tools", toolsApi({ reviewRules }));
    const region = await card("Review rules");
    await userEvent.click(within(region).getByRole("switch", { name: "Strict" }));
    await userEvent.click(within(region).getByRole("button", { name: "Run Review rules" }));
    await waitFor(() => expect(reviewRules).toHaveBeenCalledWith("doc-1", { strict: true }));
    const result = await within(region).findByRole("status", { name: "Result" });
    expect(result.textContent).toContain("Issues found");
    expect(result.textContent).toContain("Rule R1 has no evidence");
  });

  it("builds a DOCX to a chosen output path", async () => {
    const buildDocx = vi.fn(async () => ({ document_id: "doc-1", built: true, docx: "out/final.docx" }));
    openAt("/tools", toolsApi({ buildDocx }));
    const region = await card("Build DOCX");
    await userEvent.type(within(region).getByRole("textbox", { name: "Output path (optional)" }), "out/final.docx");
    await userEvent.click(within(region).getByRole("button", { name: "Run Build DOCX" }));
    await waitFor(() => expect(buildDocx).toHaveBeenCalledWith("doc-1", { output: "out/final.docx" }));
    expect((await within(region).findByRole("status")).textContent).toContain("out/final.docx");
  });

  it("explains a DOCX that could not be built instead of claiming success", async () => {
    const buildDocx = async () => ({ document_id: "doc-1", built: false, docx: null, message: "pandoc is not installed" });
    openAt("/tools", toolsApi({ buildDocx }));
    const region = await card("Build DOCX");
    await userEvent.click(within(region).getByRole("button", { name: "Run Build DOCX" }));
    expect((await within(region).findByRole("alert")).textContent).toContain("pandoc is not installed");
    expect(within(region).queryByRole("status")).toBeNull();
  });

  it("audits the DOCX format in strict mode and shows the report as text", async () => {
    const auditDocxFormat = vi.fn(async () => ({ document_id: "doc-1", docx: "d.docx", strict: true, passed: false, issues: [{ code: "fmt.font", message: "Body font differs" }], report: "# Format audit\n\nBody font differs" }));
    openAt("/tools", toolsApi({ auditDocxFormat }));
    const region = await card("Format audit DOCX");
    await userEvent.click(within(region).getByRole("switch", { name: "Strict" }));
    await userEvent.click(within(region).getByRole("button", { name: "Run Format audit DOCX" }));
    await waitFor(() => expect(auditDocxFormat).toHaveBeenCalledWith("doc-1", { strict: true }));
    const result = await within(region).findByRole("status", { name: "Result" });
    expect(result.textContent).toContain("Issues found");
    expect(within(region).getByRole("region", { name: "Audit report" }).textContent).toContain("Format audit");
  });

  it("hides a tool whose capability is unavailable and says so", async () => {
    openAt("/tools", toolsApi({ getCapabilities: async () => toolsCatalog("build-docx", "translate") }));
    await screen.findByRole("region", { name: "Collect sources" });
    expect(screen.queryByRole("region", { name: "Build DOCX" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Translate PDF" })).toBeNull();
    expect(screen.getByText(/Not available on this server: Build DOCX, Translate PDF/)).toBeTruthy();
  });

  it("asks for a document before the document tools, but not for translation", async () => {
    openAt("/tools", toolsApi({ getCurrentDocument: async () => ({ current_document_id: null, document: null }) }));
    expect(await screen.findByRole("heading", { name: "Select a document first" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Collect sources" })).toBeNull();
    expect(screen.getByRole("region", { name: "Translate PDF" })).toBeTruthy();
  });
});

describe("translation workflow", () => {
  const pdf = () => new File(["%PDF-1.4"], "manual.pdf", { type: "application/pdf" });

  it("translates a workspace artifact and links the output and provenance paths", async () => {
    const translatePdf = vi.fn(async () => ({ status: "translated", source: "manual.pdf", output: "artifacts/translations/manual.es.pdf", pending: "artifacts/translations/manual.es.pending.json", report: { blocks_total: 4, blocks_translated: 3 }, line: "3/4 blocks" }));
    openAt("/tools", toolsApi({ translatePdf }));
    const region = await card("Translate PDF");
    await userEvent.click(await within(region).findByRole("combobox", { name: "PDF artifact" }));
    await userEvent.click(await screen.findByRole("option", { name: "manual.pdf" }));
    await userEvent.type(within(region).getByRole("textbox", { name: "Target language" }), "es");
    await userEvent.click(within(region).getByRole("button", { name: "Run Translate PDF" }));
    await waitFor(() => expect(translatePdf).toHaveBeenCalledWith({ artifactId: "art-1", to: "es", sourceLang: "auto", overwrite: false }));
    const result = await within(region).findByRole("status", { name: "Translation result" });
    expect(result.textContent).toContain("Translated");
    expect(result.textContent).toContain("artifacts/translations/manual.es.pdf");
    expect(result.textContent).toContain("artifacts/translations/manual.es.pending.json");
    expect(result.textContent).toContain("3/4 blocks");
  });

  it("downloads the translated PDF through the authenticated client", async () => {
    const translatePdf = vi.fn(async () => ({ status: "translated", source: "manual.pdf", output: "artifacts/translations/manual.es.pdf" }));
    const downloadTranslation = vi.fn(async () => new Blob(["%PDF"]));
    const create = vi.fn(() => "blob:t"), revoke = vi.fn();
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    openAt("/tools", toolsApi({ translatePdf, downloadTranslation }));
    const region = await card("Translate PDF");
    await userEvent.click(await within(region).findByRole("combobox", { name: "PDF artifact" }));
    await userEvent.click(await screen.findByRole("option", { name: "manual.pdf" }));
    await userEvent.type(within(region).getByRole("textbox", { name: "Target language" }), "es");
    await userEvent.click(within(region).getByRole("button", { name: "Run Translate PDF" }));
    await userEvent.click(await within(region).findByRole("button", { name: "Download translated PDF" }));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:t"));
    expect(downloadTranslation).toHaveBeenCalledWith("artifacts/translations/manual.es.pdf");
    expect(click).toHaveBeenCalledTimes(1);
    click.mockRestore();
  });

  it("uploads a PDF with a source language", async () => {
    const translatePdf = vi.fn(async () => ({ status: "translated", source: "manual.pdf", output: "artifacts/translations/manual.es.pdf" }));
    openAt("/tools", toolsApi({ translatePdf }));
    const region = await card("Translate PDF");
    await userEvent.click(within(region).getByRole("radio", { name: "Upload a PDF" }));
    await userEvent.upload(within(region).getByLabelText("PDF file"), pdf());
    await userEvent.type(within(region).getByRole("textbox", { name: "Target language" }), "es");
    await userEvent.clear(within(region).getByRole("textbox", { name: "Source language" }));
    await userEvent.type(within(region).getByRole("textbox", { name: "Source language" }), "en");
    await userEvent.click(within(region).getByRole("button", { name: "Run Translate PDF" }));
    await waitFor(() => expect(translatePdf).toHaveBeenCalledWith(expect.objectContaining({ filename: "manual.pdf", contentBase64: expect.any(String), to: "es", sourceLang: "en", overwrite: false })));
  });

  it("replaces an existing translation only after an explicit confirmation following output_exists", async () => {
    const translatePdf = vi.fn()
      .mockRejectedValueOnce(new ApiError("The output already exists", 409, "output_exists"))
      .mockResolvedValueOnce({ status: "translated", source: "manual.pdf", output: "artifacts/translations/manual.es.pdf" });
    openAt("/tools", toolsApi({ translatePdf }));
    const region = await card("Translate PDF");
    await userEvent.click(within(region).getByRole("radio", { name: "Upload a PDF" }));
    await userEvent.upload(within(region).getByLabelText("PDF file"), pdf());
    await userEvent.type(within(region).getByRole("textbox", { name: "Target language" }), "es");
    await userEvent.click(within(region).getByRole("button", { name: "Run Translate PDF" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Replace the existing translation?" });
    expect(translatePdf).toHaveBeenCalledTimes(1);
    await userEvent.click(within(dialog).getByRole("button", { name: "Replace translation" }));
    await waitFor(() => expect(translatePdf).toHaveBeenLastCalledWith(expect.objectContaining({ overwrite: true })));
  });

  it("reports unavailable and untranslatable results honestly", async () => {
    const translatePdf = vi.fn()
      .mockResolvedValueOnce({ status: "unavailable", source: "manual.pdf", message: "Translation unavailable: the PDF adapters are missing." })
      .mockResolvedValueOnce({ status: "untranslatable", source: "manual.pdf", message: "The PDF has no text layer" });
    openAt("/tools", toolsApi({ translatePdf }));
    const region = await card("Translate PDF");
    await userEvent.click(await within(region).findByRole("combobox", { name: "PDF artifact" }));
    await userEvent.click(await screen.findByRole("option", { name: "manual.pdf" }));
    await userEvent.type(within(region).getByRole("textbox", { name: "Target language" }), "es");
    await userEvent.click(within(region).getByRole("button", { name: "Run Translate PDF" }));
    const first = await within(region).findByRole("alert");
    expect(first.textContent).toContain("PDF adapters are missing");
    expect(first.textContent).toContain("Unavailable");
    expect(within(region).queryByRole("status", { name: "Translation result" })).toBeNull();
    await userEvent.click(within(region).getByRole("button", { name: "Run Translate PDF" }));
    await waitFor(() => expect(within(region).getByRole("alert").textContent).toContain("no text layer"));
    expect(within(region).getByRole("alert").textContent).toContain("Untranslatable");
  });
});

describe("document detail and source import", () => {
  it("shows the document record and its resumable summary on the workspace page", async () => {
    const getDocumentSummary = vi.fn(async (id: string) => ({ document_id: id, summary: { stage: "assembled", sections: 2, next: "build" } }));
    openAt("/configure/workspaces", toolsApi({ getDocumentSummary, listDocuments: async () => [{ id: "doc-1", title: "Field notes" }] }));
    const detail = await screen.findByRole("region", { name: "Document details" });
    await waitFor(() => expect(getDocumentSummary).toHaveBeenCalledWith("doc-1"));
    await within(detail).findByText("Field notes");
    expect(detail.textContent).toContain("assembled");
    expect(detail.textContent).toContain("build");
    expect(detail.textContent).not.toMatch(/[{}]/);
  });

  it("imports a source file into the document from the authoring Sources tab", async () => {
    const importSourceFile = vi.fn(async (id: string, input: { filename: string }) => ({ document_id: id, filename: input.filename, path: `documents/${id}/imports/${input.filename}`, sha256: "f".repeat(64), size: 3, mime_type: "text/markdown", deduplicated: true }));
    openAt("/authoring/sources", toolsApi({ importSourceFile }));
    const form = await screen.findByRole("region", { name: "Import source file" });
    await userEvent.upload(within(form).getByLabelText("Source file"), new File(["abc"], "notes.md", { type: "text/markdown" }));
    await userEvent.click(within(form).getByRole("button", { name: "Import source file" }));
    await waitFor(() => expect(importSourceFile).toHaveBeenCalledWith("doc-1", { filename: "notes.md", content_base64: "YWJj" }));
    const result = await within(form).findByRole("status");
    expect(result.textContent).toContain("documents/doc-1/imports/notes.md");
    expect(result.textContent).toContain("Already imported");
  });

  it("hides source import when the capability is unavailable", async () => {
    openAt("/authoring/sources", toolsApi({ getCapabilities: async () => toolsCatalog("document.import") }));
    await screen.findByRole("heading", { name: "Sources" });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Import source file" })).toBeNull());
  });
});
