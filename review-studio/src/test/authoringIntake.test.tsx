// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { catalogWithout, makeApi, openAuthoring } from "./authoringHarness";

afterEach(() => { cleanup(); window.location.hash = ""; });

describe("authoring prerequisites", () => {
  it("asks for a document instead of guessing one", async () => {
    openAuthoring("sections", makeApi({ getCurrentDocument: async () => ({ current_document_id: null, document: null }) }));
    expect(await screen.findByRole("heading", { name: "Select a document first" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open workspaces and documents" }).getAttribute("href")).toContain("/configure/workspaces");
    expect(screen.queryByRole("tab", { name: "Sections" })).toBeNull();
  });

  it("shows the active workspace and document and an Add sources hint from server data only", async () => {
    openAuthoring("sources", makeApi({ listDocumentSections: async () => [] }));
    const bar = await screen.findByRole("region", { name: "Active context" });
    expect(bar.textContent).toContain("Research");
    expect(bar.textContent).toContain("doc-1");
    expect(await within(bar).findByRole("link", { name: "Add sources" })).toBeTruthy();
  });

  it("hides an action whose capability is not available", async () => {
    openAuthoring("assets", makeApi({ getCapabilities: async () => catalogWithout("asset.add") }));
    await screen.findByRole("heading", { name: "Assets" });
    await waitFor(() => expect(screen.getByText(/Adding assets is not available/)).toBeTruthy());
    expect(screen.queryByRole("button", { name: "Add asset" })).toBeNull();
  });
});

describe("source intake", () => {
  it("uploads a file as base64 and renders each ingest stage", async () => {
    const ingestSources = vi.fn(async () => ({
      document_id: "doc-1", succeeded: true, artifacts: [],
      uploaded: [{ filename: "notes.md", sha256: "abc", size: 5, deduplicated: false }],
      stages: [{ name: "convert", succeeded: true, status: "done", processed: 1, errors: [], warnings: ["Low contrast scan"], files: [{ name: "notes.md" }] }],
    }));
    openAuthoring("sources", makeApi({ ingestSources }));
    await userEvent.upload(await screen.findByLabelText("Source files"), new File(["hello"], "notes.md", { type: "text/markdown" }));
    await userEvent.click(screen.getByRole("button", { name: "Ingest sources" }));
    await waitFor(() => expect(ingestSources).toHaveBeenCalledWith("doc-1", [{ filename: "notes.md", content_base64: btoa("hello") }]));
    const result = await screen.findByRole("region", { name: "Ingest result" });
    expect(within(result).getByText("Succeeded")).toBeTruthy();
    expect(within(result).getByText("convert")).toBeTruthy();
    expect(within(result).getByText("Low contrast scan")).toBeTruthy();
  });

  it("shows the server errors of a failed stage with recovery guidance", async () => {
    const ingestSources = async () => ({
      document_id: "doc-1", succeeded: false, artifacts: [], uploaded: [],
      stages: [{ name: "convert", succeeded: false, status: "failed", processed: 0, errors: ["Corrupt PDF header in broken.pdf"], warnings: [], files: [] }],
    });
    openAuthoring("sources", makeApi({ ingestSources }));
    await userEvent.click(await screen.findByRole("button", { name: "Ingest sources" }));
    const result = await screen.findByRole("region", { name: "Ingest result" });
    expect(within(result).getByText("Failed")).toBeTruthy();
    expect(within(result).getByText("Corrupt PDF header in broken.pdf")).toBeTruthy();
    expect(within(result).getByText(/replace the failing source/i)).toBeTruthy();
  });

  it("surfaces a rejected request with a retry", async () => {
    const ingestSources = vi.fn().mockRejectedValueOnce(new ApiError("Source is not a valid document", 422, "invalid_source")).mockResolvedValue({ document_id: "doc-1", succeeded: true, artifacts: [], uploaded: [], stages: [] });
    openAuthoring("sources", makeApi({ ingestSources }));
    await userEvent.click(await screen.findByRole("button", { name: "Ingest sources" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Source is not a valid document");
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(ingestSources).toHaveBeenCalledTimes(2));
  });
});

describe("classification", () => {
  it("confirms the role of a pending source", async () => {
    const confirmDocumentClassification = vi.fn(async () => ({}));
    openAuthoring("classification", makeApi({
      getDocumentClassification: async id => ({ document_id: id, items: [{ relative_path: "inbox/a.md", proposed_role: "evidence", confidence: 0.9 }] }),
      confirmDocumentClassification,
    }));
    await userEvent.click(await screen.findByRole("combobox", { name: "Role for inbox/a.md" }));
    await userEvent.click(await screen.findByRole("option", { name: "normative" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm role for inbox/a.md" }));
    await waitFor(() => expect(confirmDocumentClassification).toHaveBeenCalledWith("doc-1", { relative_path: "inbox/a.md", confirmed_role: "normative" }));
  });

  it("explains that nothing is pending when the queue is unavailable", async () => {
    openAuthoring("classification", makeApi({ getDocumentClassification: async () => { throw new ApiError("none", 404, "classification_unavailable"); } }));
    expect(await screen.findByRole("heading", { name: "No classification pending" })).toBeTruthy();
  });
});

describe("assets", () => {
  const withAsset = (removeAsset = vi.fn(async () => ({ document_id: "doc-1", removed: "logo.png" }))) => makeApi({
    listAssets: async (id: string) => ({ document_id: id, kind: "", items: [{ name: "logo.png" }] }), removeAsset,
  });

  it("removes an asset only after confirmation and shows server errors", async () => {
    const removeAsset = vi.fn().mockRejectedValueOnce(new ApiError("Asset is referenced", 409, "asset_in_use")).mockResolvedValue({ document_id: "doc-1", removed: "logo.png" });
    openAuthoring("assets", withAsset(removeAsset));
    await userEvent.click(await screen.findByRole("button", { name: "Remove logo.png" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(removeAsset).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove asset" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("Asset is referenced");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove asset" }));
    await waitFor(() => expect(removeAsset).toHaveBeenCalledTimes(2));
    expect(removeAsset).toHaveBeenLastCalledWith("doc-1", "logo.png");
  });

  it("cancels removal and returns focus to the trigger", async () => {
    const removeAsset = vi.fn();
    openAuthoring("assets", withAsset(removeAsset));
    const trigger = await screen.findByRole("button", { name: "Remove logo.png" });
    await userEvent.click(trigger);
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(removeAsset).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("context", () => {
  it("sets a context value for a topic", async () => {
    const setDocumentContext = vi.fn(async () => ({}));
    openAuthoring("context", makeApi({
      getDocumentContext: async id => ({ document_id: id, topics: [{ id: "project", title: "Project", required: true, exists: false, missing: true, fields: [{ key: "name", label: "Name" }] }] }),
      setDocumentContext,
    }));
    expect(await screen.findByText("Missing")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Set value for project" }));
    await userEvent.type(screen.getByLabelText("Value"), "Atlas");
    await userEvent.click(screen.getByRole("button", { name: "Set context value" }));
    await waitFor(() => expect(setDocumentContext).toHaveBeenCalledWith("doc-1", { topic: "project", field: "name", value: "Atlas" }));
  });
});
