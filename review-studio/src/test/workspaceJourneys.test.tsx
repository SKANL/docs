// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { ReviewApi, Workspace } from "../api/models";

const workspace: Workspace = { id: "workspace-a", name: "Research", root: "C:/data/research" };
const document = { id: "field-notes", title: "Field notes", template: "documento-generico", active: false };

function makeApi(overrides: Partial<ReviewApi> = {}): ReviewApi {
  return {
    listFindings: async () => [], listArtifacts: async () => [],
    getGraph: async () => ({ nodes: [], edges: [] }), getGraphQuery: async () => ({ items: [], graphUnavailable: false }),
    listTemplates: async () => [{ id: "documento-generico", name: "Generic document" }], listBaselines: async () => [],
    listRevisions: async () => [],
    listWorkspaces: async () => [workspace], selectWorkspace: async () => workspace,
    createWorkspace: async input => ({ ...workspace, name: input.name }),
    renameWorkspace: async (_id, name) => ({ ...workspace, name }), deleteWorkspace: async id => ({ deleted: id }),
    getWorkspaceStatus: async id => ({ workspace: { ...workspace, id }, active: id === workspace.id }),
    listDocuments: async () => [document], getCurrentDocument: async () => ({ current_document_id: null, document: null }),
    useDocument: async id => ({ ...document, id, active: true }),
    createDocument: async input => ({ id: input.documentId, title: input.title, template: input.template, active: true }),
    renameDocument: async (_id, newId) => ({ ...document, id: newId }),
    deleteDocument: async id => ({ deleted: id, current_document_id: null }),
    getDocumentStatus: async id => ({ document_id: id, succeeded: true, capabilities: [], publication_blockers: [] }),
    ...overrides,
  } as ReviewApi;
}

afterEach(() => {
  cleanup();
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  window.location.hash = "";
  localStorage.clear();
});

describe("workspace and document journeys", () => {
  it("creates a workspace and makes it the selected context", async () => {
    const workspaces = [workspace];
    const createWorkspace = vi.fn(async input => { const created = { ...workspace, id: "workspace-new", name: input.name }; workspaces.unshift(created); return created; }); // the server selects a new workspace and lists the selected one first
    window.location.hash = "#/configure/workspaces";
    render(<App api={makeApi({ listWorkspaces: async () => workspaces, createWorkspace })} />);

    await screen.findByRole("heading", { name: "Workspace and document control" }, { timeout: 5000 });
    await screen.findByRole("combobox", { name: "Active workspace" }); // the workspace list loads after the page renders
    fireEvent.click(await screen.findByRole("button", { name: "Create workspace" }));
    const dialog = await screen.findByRole("dialog", { name: "Create workspace" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Workspace name" }), { target: { value: "Studio" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create workspace" }));

    await waitFor(() => expect(createWorkspace).toHaveBeenCalledWith({ name: "Studio" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Active workspace" }).textContent).toContain("Studio"));
  });

  it("renames a workspace and recovers after a transient rename error", async () => {
    let renamed = false;
    const renameWorkspace = vi.fn(async (_id: string, name: string) => {
      if (!renamed) { renamed = true; throw new Error("Workspace service is temporarily unavailable"); }
      return { ...workspace, name };
    });
    window.location.hash = "#/configure/workspaces";
    render(<App api={makeApi({ renameWorkspace })} />);

    await screen.findByRole("heading", { name: "Workspace and document control" });
    await screen.findByRole("combobox", { name: "Active workspace" }); // the workspace list loads after the page renders
    fireEvent.click(screen.getByRole("button", { name: "Rename workspace" }));
    const dialog = await screen.findByRole("dialog", { name: "Rename workspace" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Workspace name" }), { target: { value: "Renamed research" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Rename workspace" }));

    expect((await within(dialog).findByRole("alert")).textContent).toContain("temporarily unavailable");
    fireEvent.click(within(dialog).getByRole("button", { name: "Rename workspace" }));
    await waitFor(() => expect(renameWorkspace).toHaveBeenLastCalledWith(workspace.id, "Renamed research"));
    expect(await screen.findByText("Workspace name updated.")).toBeTruthy();
  });

  it("confirms workspace deletion and recovers after a transient delete error", async () => {
    let deleted = false;
    const remaining = { ...workspace, id: "workspace-b", name: "Second workspace" };
    const deleteWorkspace = vi.fn(async (id: string) => {
      if (!deleted) { deleted = true; throw new Error("Workspace service is temporarily unavailable"); }
      return { deleted: id };
    });
    const selectWorkspace = vi.fn(async () => remaining);
    window.location.hash = "#/configure/workspaces";
    render(<App api={makeApi({ listWorkspaces: async () => [workspace, remaining], deleteWorkspace, selectWorkspace })} />);

    await screen.findByRole("heading", { name: "Workspace and document control" });
    await screen.findByRole("combobox", { name: "Active workspace" }); // the workspace list loads after the page renders
    fireEvent.click(screen.getByRole("button", { name: "Delete workspace" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete workspace" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete workspace" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("temporarily unavailable");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete workspace" }));

    await waitFor(() => expect(deleteWorkspace).toHaveBeenLastCalledWith(workspace.id));
    await waitFor(() => expect(selectWorkspace).toHaveBeenCalledWith(remaining.id));
    expect(await screen.findByText("Workspace deleted.")).toBeTruthy();
  });

  it("creates and selects a document, then supports rename and confirmed deletion", async () => {
    const docs = [document];
    let currentId: string | null = null;
    const createDocument = vi.fn(async input => { const created = { id: input.documentId, title: input.title, template: input.template, active: true }; docs.push(created); return created; });
    const useDocument = vi.fn(async id => { currentId = id; return { ...docs.find(item => item.id === id)!, active: true }; });
    const renameDocument = vi.fn(async (id, newId) => { const item = docs.find(candidate => candidate.id === id)!; const renamed = { ...item, id: newId }; docs[docs.indexOf(item)] = renamed; if (currentId === id) currentId = newId; return renamed; });
    const deleteDocument = vi.fn(async id => { docs.splice(docs.findIndex(item => item.id === id), 1); if (currentId === id) currentId = null; return { deleted: id, current_document_id: currentId }; });
    window.location.hash = "#/configure/workspaces";
    render(<App api={makeApi({ listDocuments: async () => [...docs], getCurrentDocument: async () => ({ current_document_id: currentId, document: docs.find(item => item.id === currentId) ?? null }), createDocument, useDocument, renameDocument, deleteDocument })} />);

    await screen.findByRole("heading", { name: "Workspace and document control" });
    await screen.findByRole("combobox", { name: "Active workspace" }); // the workspace list loads after the page renders
    fireEvent.click(screen.getByRole("button", { name: "Create document" }));
    const createDialog = await screen.findByRole("dialog", { name: "Create document" });
    fireEvent.change(within(createDialog).getByRole("textbox", { name: "Document ID" }), { target: { value: "new-notes" } });
    fireEvent.change(within(createDialog).getByRole("textbox", { name: "Title" }), { target: { value: "New notes" } });
    fireEvent.click(within(createDialog).getByRole("button", { name: "Create document" }));
    await waitFor(() => expect(createDocument).toHaveBeenCalledWith({ workspaceId: workspace.id, documentId: "new-notes", title: "New notes", template: "documento-generico" }));

    fireEvent.click(await screen.findByRole("button", { name: "Use field-notes" }));
    await waitFor(() => expect(useDocument).toHaveBeenCalledWith("field-notes", workspace.id));
    fireEvent.click(screen.getByRole("button", { name: "Rename field-notes" }));
    const renameDialog = await screen.findByRole("dialog", { name: "Rename document" });
    fireEvent.change(within(renameDialog).getByRole("textbox", { name: "New document ID" }), { target: { value: "field-notes-2026" } });
    fireEvent.click(within(renameDialog).getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(renameDocument).toHaveBeenCalledWith("field-notes", "field-notes-2026", workspace.id));

    fireEvent.click(await screen.findByRole("button", { name: "Delete field-notes-2026" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Delete document" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(deleteDocument).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete field-notes-2026" }));
    const confirmAgain = await screen.findByRole("alertdialog", { name: "Delete document" });
    fireEvent.click(within(confirmAgain).getByRole("button", { name: "Delete document" }));
    await waitFor(() => expect(deleteDocument).toHaveBeenCalledWith("field-notes-2026", workspace.id));
  });

  it("explains that workspace selection is unavailable when the API has no selection capability", async () => {
    window.location.hash = "#/configure/workspaces";
    const secondWorkspace = { ...workspace, id: "workspace-b", name: "Writing" };
    render(<App api={makeApi({ listWorkspaces: async () => [workspace, secondWorkspace], selectWorkspace: undefined })} />);

    const selector = await screen.findByRole("combobox", { name: "Active workspace" });
    expect(selector.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/Workspace selection is unavailable/).textContent).toContain("Workspace selection is unavailable");
  });

  it("does not claim a newly created document was selected when selection is unsupported", async () => {
    window.location.hash = "#/configure/workspaces";
    render(<App api={makeApi({ useDocument: undefined })} />);

    await screen.findByRole("heading", { name: "Workspace and document control" });
    await screen.findByRole("combobox", { name: "Active workspace" }); // the workspace list loads after the page renders
    fireEvent.click(screen.getByRole("button", { name: "Create document" }));
    const dialog = await screen.findByRole("dialog", { name: "Create document" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Document ID" }), { target: { value: "not-selectable" } });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Title" }), { target: { value: "Created only" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create document" }));

    expect(await screen.findByText(/created, but selection is unavailable/)).toBeTruthy();
    expect(screen.queryByText("Document Created only created and selected.")).toBeNull();
  });

  it("allows closing pending creation dialogs and prevents a duplicate submission", async () => {
    let finishCreate!: (created: typeof workspace) => void;
    const createWorkspace = vi.fn(() => new Promise<typeof workspace>(resolve => { finishCreate = resolve; }));
    window.location.hash = "#/configure/workspaces";
    render(<App api={makeApi({ createWorkspace })} />);

    await screen.findByRole("heading", { name: "Workspace and document control" });
    await screen.findByRole("combobox", { name: "Active workspace" }); // the workspace list loads after the page renders
    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
    const dialog = await screen.findByRole("dialog", { name: "Create workspace" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Workspace name" }), { target: { value: "Pending workspace" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create workspace" }));
    expect(await within(dialog).findByText(/cannot be cancelled/i)).toBeTruthy();
    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Create workspace" })).toBeNull());
    expect(createWorkspace).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Create workspace" }).hasAttribute("disabled")).toBe(true);
    finishCreate({ ...workspace, id: "workspace-pending", name: "Pending workspace" });
    await screen.findByText("Workspace Pending workspace created.");
  });

  it("allows closing a pending document dialog without resubmitting its mutation", async () => {
    let finishCreate!: (created: Record<string, unknown>) => void;
    const createDocument = vi.fn(() => new Promise<Record<string, unknown>>(resolve => { finishCreate = resolve; }));
    window.location.hash = "#/configure/workspaces";
    render(<App api={makeApi({ createDocument })} />);

    await screen.findByRole("heading", { name: "Workspace and document control" });
    await screen.findByRole("combobox", { name: "Active workspace" }); // the workspace list loads after the page renders
    fireEvent.click(screen.getByRole("button", { name: "Create document" }));
    const dialog = await screen.findByRole("dialog", { name: "Create document" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Document ID" }), { target: { value: "pending-document" } });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Title" }), { target: { value: "Pending document" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create document" }));
    expect(await within(dialog).findByText(/cannot be cancelled/i)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Create document" })).toBeNull());
    expect(createDocument).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Create document" }).hasAttribute("disabled")).toBe(true);
    finishCreate({ id: "pending-document", title: "Pending document", template: "documento-generico" });
    await screen.findByText("Document Pending document created and selected.");
  });

  it("offers an explicit retry when document status loading fails", async () => {
    let attempts = 0;
    const getDocumentStatus = vi.fn(async () => {
      attempts += 1;
      if (attempts === 1) throw new Error("Status service unavailable");
      return { document_id: document.id, succeeded: true, capabilities: [], publication_blockers: [] };
    });
    window.location.hash = "#/configure/workspaces";
    render(<App api={makeApi({ getCurrentDocument: async () => ({ current_document_id: document.id, document }), getDocumentStatus })} />);

    const retry = await screen.findByRole("button", { name: "Retry document status" });
    expect(screen.getByRole("alert").textContent).toContain("Status service unavailable");
    fireEvent.click(retry);

    await waitFor(() => expect(getDocumentStatus).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Ready")).toBeTruthy();
  });

  it("keeps the shared workspace journey and reports desktop-local bootstrap in Tauri", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true });
    window.location.hash = "#/configure/workspaces";
    render(<App api={makeApi()} />);

    expect(await screen.findByRole("heading", { name: "Workspace and document control" })).toBeTruthy();
    expect(screen.getByText(/Desktop storage is prepared in app data/)).toBeTruthy();
    expect(await screen.findByRole("combobox", { name: "Active workspace" })).toBeTruthy();
  });
});
