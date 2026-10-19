// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeApi, openAuthoring } from "./authoringHarness";
import { toolsApi, toolsCatalog, openAt } from "./toolsHarness";
import { openPipeline, streamingApi } from "./pipelineHarness";

beforeEach(() => localStorage.setItem("review-studio.mode", "supervise"));
afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); });
const md = (name: string) => new File(["abc"], name, { type: "text/markdown" });
const stored = (id: string, input: { filename: string }) => ({ document_id: id, filename: input.filename, path: `documents/${id}/imports/${input.filename}`, sha256: "f".repeat(64), size: 3, mime_type: "text/markdown", deduplicated: false });

describe("Sources import", () => {
  it("keeps the files that were stored when another one fails, and names the failure", async () => {
    const importSourceFile = vi.fn(async (id: string, input: { filename: string }) => { if (input.filename === "bad.md") throw new Error("disk full"); return stored(id, input); });
    localStorage.setItem("review-studio.advanced", "true");
    openAt("/authoring/sources", toolsApi({ importSourceFile, ingestSources: async () => ({}) }));
    await userEvent.upload(await screen.findByLabelText("Source files"), [md("ok.md"), md("bad.md")]);
    await userEvent.click(screen.getByRole("button", { name: "Import without converting" }));
    expect(await screen.findByText("documents/doc-1/imports/ok.md")).toBeTruthy();
    expect((await screen.findByRole("alert")).textContent).toContain("bad.md");
  });

  it("clears the file input after an import so the form does not show stale files", async () => {
    localStorage.setItem("review-studio.advanced", "true");
    openAt("/authoring/sources", toolsApi({ ingestSources: async () => ({}) }));
    await userEvent.upload(await screen.findByLabelText("Source files"), md("a.md"));
    await userEvent.click(screen.getByRole("button", { name: "Import without converting" }));
    await screen.findByText("documents/doc-1/imports/a.md");
    expect((screen.getByLabelText("Source files") as HTMLInputElement).files).toHaveLength(0);
  });

  it("stays available when only document.import exists", async () => {
    const importSourceFile = vi.fn(async (id: string, input: { filename: string }) => stored(id, input));
    localStorage.setItem("review-studio.advanced", "true");
    openAt("/authoring/sources", toolsApi({ getCapabilities: async () => toolsCatalog("source.ingest"), importSourceFile }));
    await userEvent.upload(await screen.findByLabelText("Source files"), md("a.md"));
    expect(screen.queryByRole("button", { name: "Ingest sources" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Import without converting" }));
    await waitFor(() => expect(importSourceFile).toHaveBeenCalled());
  });
});

describe("Sections editing", () => {
  const body = () => screen.findByRole("textbox", { name: "Section body" }) as Promise<HTMLTextAreaElement>;
  it("returns to read-only when another section is opened", async () => {
    openAuthoring("sections", makeApi());
    await userEvent.click(await screen.findByRole("button", { name: "Edit section" }));
    expect((await body()).readOnly).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "summary" }));
    expect((await body()).readOnly).toBe(true);
    expect(screen.getByRole("button", { name: "Edit section" })).toBeTruthy();
  });
  it("returns to read-only when the working mode changes", async () => {
    openAuthoring("sections", makeApi());
    await userEvent.click(await screen.findByRole("button", { name: "Edit section" }));
    const group = screen.getByRole("group", { name: "Working mode" });
    await userEvent.click(within(group).getByRole("button", { name: "Write" }));
    await userEvent.click(within(group).getByRole("button", { name: "Supervise" }));
    expect((await body()).readOnly).toBe(true);
  });
});

describe("Pipeline policy", () => {
  it("falls back to draft when Advanced is turned off while release is selected", async () => {
    const runDocument = vi.fn(async () => ({ id: "r1" }));
    localStorage.setItem("review-studio.advanced", "true");
    openPipeline("/pipeline", streamingApi({ runDocument } as never).api);
    await userEvent.click(await screen.findByRole("combobox", { name: "Policy" }));
    await userEvent.click(await screen.findByRole("option", { name: "release" }));
    await userEvent.click(screen.getByRole("switch", { name: "Advanced" }));
    await userEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    await waitFor(() => expect(runDocument).toHaveBeenCalledWith("doc-1", { format: "docx", policy: "draft" }));
  });
});
