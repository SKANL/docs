// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { openAt, toolsApi, toolsCatalog } from "./toolsHarness";

afterEach(() => { cleanup(); window.location.hash = ""; });

describe("template editor", () => {
  it("lists installed templates and the built-in catalogue with install state", async () => {
    openAt("/configure/templates", toolsApi());
    const installed = await screen.findByRole("table", { name: "Installed templates" });
    expect(within(installed).getByText("report")).toBeTruthy();
    const catalogue = await screen.findByRole("table", { name: "Built-in catalogue" });
    expect(within(catalogue).getByText("memo").closest("tr")?.textContent).toContain("Not installed");
    expect(within(catalogue).getByText("report").closest("tr")?.textContent).toContain("Installed");
  });

  it("shows a template structurally, never as raw JSON", async () => {
    const showTemplate = vi.fn(async (name: string) => ({ name, template: { title: "Report", sections: [{ id: "intro", title: "Intro" }] } }));
    openAt("/configure/templates", toolsApi({ showTemplate }));
    await userEvent.click(await screen.findByRole("button", { name: "Show report" }));
    const view = await screen.findByRole("region", { name: "Template structure" });
    expect(showTemplate).toHaveBeenCalledWith("report");
    expect(view.textContent).toContain("Intro");
    expect(view.textContent).toContain("sections");
    expect(view.textContent).not.toMatch(/[{}]/);
  });

  it("installs a built-in template without forcing", async () => {
    const installBuiltinTemplate = vi.fn(async (name: string) => ({ name, path: `templates/${name}.json` }));
    openAt("/configure/templates", toolsApi({ installBuiltinTemplate }));
    await userEvent.click(await screen.findByRole("button", { name: "Install memo" }));
    await waitFor(() => expect(installBuiltinTemplate).toHaveBeenCalledWith("memo", { force: false }));
    expect(await screen.findByText("Installed memo at templates/memo.json.")).toBeTruthy();
  });

  it("overwrites an installed template only after an explicit confirmation following template_exists", async () => {
    const installBuiltinTemplate = vi.fn()
      .mockRejectedValueOnce(new ApiError("Template already exists", 409, "template_exists"))
      .mockResolvedValueOnce({ name: "memo", path: "templates/memo.json" });
    openAt("/configure/templates", toolsApi({ installBuiltinTemplate }));
    await userEvent.click(await screen.findByRole("button", { name: "Install memo" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Replace memo?" });
    expect(installBuiltinTemplate).toHaveBeenCalledTimes(1);
    await userEvent.click(within(dialog).getByRole("button", { name: "Replace template" }));
    await waitFor(() => expect(installBuiltinTemplate).toHaveBeenLastCalledWith("memo", { force: true }));
  });

  it("keeps the existing template when the overwrite is cancelled", async () => {
    const installBuiltinTemplate = vi.fn().mockRejectedValue(new ApiError("Template already exists", 409, "template_exists"));
    openAt("/configure/templates", toolsApi({ installBuiltinTemplate }));
    await userEvent.click(await screen.findByRole("button", { name: "Install memo" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Replace memo?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(installBuiltinTemplate).toHaveBeenCalledTimes(1);
  });

  it("creates a new empty template skeleton", async () => {
    const createTemplate = vi.fn(async (name: string) => ({ name, path: `templates/${name}.json` }));
    openAt("/configure/templates", toolsApi({ createTemplate }));
    await userEvent.type(await screen.findByRole("textbox", { name: "New template name" }), "fresh");
    await userEvent.click(screen.getByRole("button", { name: "Create template" }));
    await waitFor(() => expect(createTemplate).toHaveBeenCalledWith("fresh"));
    expect(await screen.findByText("Created fresh at templates/fresh.json.")).toBeTruthy();
  });

  it("shows the server name error when a template cannot be created", async () => {
    const createTemplate = async () => { throw new ApiError("Invalid template name", 400, "invalid_template_name"); };
    openAt("/configure/templates", toolsApi({ createTemplate }));
    await userEvent.type(await screen.findByRole("textbox", { name: "New template name" }), "bad name");
    await userEvent.click(screen.getByRole("button", { name: "Create template" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Invalid template name");
  });

  it("hides template actions whose capability is unavailable", async () => {
    openAt("/configure/templates", toolsApi({ getCapabilities: async () => toolsCatalog("template.use", "template.create", "template.init", "template.validate", "template.show") }));
    await screen.findByRole("table", { name: "Installed templates" });
    expect(screen.queryByRole("button", { name: "Install memo" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Create template" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show report" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Validate" })).toBeNull();
  });
});

describe("template validation", () => {
  it("lists validation issues as messages, not raw JSON", async () => {
    const validateTemplate = vi.fn(async (name: string) => ({ name, passed: false, issues: [{ code: "template.section_missing", severity: "error", message: "Section intro has no title" }] }));
    openAt("/configure/templates", toolsApi({ validateTemplate }));
    const panel = await screen.findByRole("region", { name: "Validate template" });
    await userEvent.type(within(panel).getByRole("textbox", { name: "Template name" }), "report");
    await userEvent.click(within(panel).getByRole("button", { name: "Validate" }));
    await waitFor(() => expect(validateTemplate).toHaveBeenCalledWith("report", undefined));
    const result = await screen.findByRole("status", { name: "Validation result" });
    expect(result.textContent).toContain("Issues found");
    expect(result.textContent).toContain("Section intro has no title");
    expect(result.textContent).toContain("template.section_missing");
    expect(result.textContent).not.toMatch(/[{}]/);
  });

  it("reports a passing template as passed", async () => {
    openAt("/configure/templates", toolsApi());
    const panel = await screen.findByRole("region", { name: "Validate template" });
    await userEvent.type(within(panel).getByRole("textbox", { name: "Template name" }), "report");
    await userEvent.click(within(panel).getByRole("button", { name: "Validate" }));
    expect((await screen.findByRole("status", { name: "Validation result" })).textContent).toContain("Passed");
  });

  it("validates a pasted draft without storing it", async () => {
    const validateTemplate = vi.fn(async (name: string) => ({ name, passed: true, issues: [] }));
    openAt("/configure/templates", toolsApi({ validateTemplate }));
    const panel = await screen.findByRole("region", { name: "Validate template" });
    await userEvent.type(within(panel).getByRole("textbox", { name: "Template name" }), "report");
    fireJson(within(panel).getByRole("textbox", { name: "Draft JSON (optional)" }), '{"sections": []}');
    await userEvent.click(within(panel).getByRole("button", { name: "Validate" }));
    await waitFor(() => expect(validateTemplate).toHaveBeenCalledWith("report", { sections: [] }));
  });

  it("rejects a draft that is not a JSON object before sending anything", async () => {
    const validateTemplate = vi.fn();
    openAt("/configure/templates", toolsApi({ validateTemplate }));
    const panel = await screen.findByRole("region", { name: "Validate template" });
    await userEvent.type(within(panel).getByRole("textbox", { name: "Template name" }), "report");
    fireJson(within(panel).getByRole("textbox", { name: "Draft JSON (optional)" }), "[1, 2");
    await userEvent.click(within(panel).getByRole("button", { name: "Validate" }));
    expect((await within(panel).findByRole("alert")).textContent).toContain("The draft is not valid JSON");
    expect(validateTemplate).not.toHaveBeenCalled();
  });
});

/** userEvent.type treats braces and brackets as key syntax; set the value directly instead. */
function fireJson(element: HTMLElement, value: string) {
  const area = element as HTMLTextAreaElement;
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
  setter.call(area, value);
  area.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("diagnostics", () => {
  it("lists every check with a status badge and its version", async () => {
    const getDiagnostics = async () => ({ document_id: "doc-1", passed: false, strict: false, capabilities: {}, capability_diagnostics: {}, checks: [
      { name: "pandoc", status: "ok", required: true, detail: "pandoc (3.1)", version: "3.1" },
      { name: "libreoffice", status: "unavailable", required: false, detail: "not found", version: null },
      { name: "templates", status: "error", required: true, detail: "missing", version: null },
      { name: "fonts", status: "warn", required: false, detail: "substituted", version: null },
    ] });
    openAt("/configure/diagnostics", toolsApi({ getDiagnostics }));
    const table = await screen.findByRole("table", { name: "Diagnostic checks" });
    const row = (name: string) => within(table).getByText(name).closest("tr")!.textContent!;
    expect(row("pandoc")).toContain("ok");
    expect(row("pandoc")).toContain("3.1");
    expect(row("libreoffice")).toContain("unavailable");
    expect(row("templates")).toContain("error");
    expect(row("fonts")).toContain("warn");
  });

  it("explains a degraded capability instead of calling it healthy", async () => {
    const getDiagnostics = async () => ({ document_id: "doc-1", passed: true, strict: false, checks: [], capabilities: { pdf_render: false }, capability_diagnostics: { pdf_render: "pypdfium2 is not installed" } });
    openAt("/configure/diagnostics", toolsApi({ getDiagnostics }));
    const degraded = await screen.findByRole("region", { name: "Degraded capabilities" });
    expect(degraded.textContent).toContain("pdf_render");
    expect(degraded.textContent).toContain("pypdfium2 is not installed");
  });

  it("says so when the diagnostics need a document", async () => {
    const getDiagnostics = async () => { throw new ApiError("No document is active; pass document_id", 409, "no_active_document"); };
    openAt("/configure/diagnostics", toolsApi({ getDiagnostics }));
    expect((await screen.findByRole("alert")).textContent).toContain("No document is active");
  });

  it("explains an issue code with its meaning and fix", async () => {
    const explainIssueCode = vi.fn(async (code: string) => ({ code, family: "QA", family_description: "Quality gates", meaning: "Contrast is too low", fix: "Darken the text" }));
    openAt("/configure/diagnostics", toolsApi({ explainIssueCode }));
    await userEvent.type(await screen.findByRole("textbox", { name: "Issue code" }), "QA.001");
    await userEvent.click(screen.getByRole("button", { name: "Explain code" }));
    const result = await screen.findByRole("region", { name: "Issue code explanation" });
    expect(explainIssueCode).toHaveBeenCalledWith("QA.001");
    expect(result.textContent).toContain("Contrast is too low");
    expect(result.textContent).toContain("Darken the text");
  });

  it("reports an unknown issue code honestly", async () => {
    const explainIssueCode = async () => { throw new ApiError("Unknown issue code", 404, "issue_code_not_found"); };
    openAt("/configure/diagnostics", toolsApi({ explainIssueCode }));
    await userEvent.type(await screen.findByRole("textbox", { name: "Issue code" }), "NOPE.1");
    await userEvent.click(screen.getByRole("button", { name: "Explain code" }));
    expect((await screen.findAllByRole("alert")).map(item => item.textContent).join(" ")).toContain("Unknown issue code");
  });
});

describe("plugins", () => {
  it("lists plugins read-only and states that they are never executed", async () => {
    openAt("/configure/plugins", toolsApi());
    expect((await screen.findByText(/never executed/)).textContent).toContain("plugins");
    const table = await screen.findByRole("table", { name: "Plugins" });
    expect(table.textContent).toContain("pdf-helper");
    expect(screen.queryByRole("button", { name: /run|execute|install/i })).toBeNull();
  });

  it("shows one plugin's trust and digest", async () => {
    openAt("/configure/plugins", toolsApi());
    await userEvent.click(await screen.findByRole("button", { name: "Details for pdf-helper" }));
    const detail = await screen.findByRole("region", { name: "Plugin detail" });
    expect(detail.textContent).toContain("unsigned");
    expect(detail.textContent).toContain("abc");
  });
});
