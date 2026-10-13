// Typed client for workspaces and the document lifecycle (list, create, select, rename, delete, import, status).
import { docPath, jsonInit, listPage, toPage, type Transport } from "../http";

export type Workspace = { id: string; name: string; root: string };
export type WorkspaceStatus = { workspace: Workspace; active: boolean };
export type WorkspaceMigration = { source_workspace_id: string; detected_format: string; ready: boolean; published: boolean; workspace?: Workspace | null; errors: string[] };
export type DocumentRecord = { id: string; title?: string; template?: string; lifecycle?: string; path?: string; active?: boolean; created_at?: string };
export type CurrentDocument = { current_document_id: string | null; document: DocumentRecord | null };
export type ImportResult = { id: string; document_id: string; filename: string; path: string; mime_type: string; size: number; sha256: string; deduplicated?: boolean };
export type DocumentCreateInput = { workspaceId: string; documentId: string; template: string; title?: string };
export type DocumentDeleted = { deleted: string; current_document_id: string | null };

export interface WorkspacesApi {
  listWorkspaces(): Promise<Workspace[]>;
  createWorkspace(input: { name: string }): Promise<Workspace>;
  renameWorkspace(id: string, name: string): Promise<Workspace>;
  deleteWorkspace(id: string): Promise<Record<string, unknown>>;
  getWorkspaceStatus(id: string): Promise<WorkspaceStatus>;
  migrateWorkspace(id: string, input: { apply: boolean }): Promise<WorkspaceMigration>;
  selectWorkspace(id: string): Promise<Workspace>;
  listDocuments(workspaceId?: string): Promise<DocumentRecord[]>;
  getDocument(id: string): Promise<Record<string, unknown>>;
  getCurrentDocument(workspaceId: string): Promise<CurrentDocument>;
  useDocument(id: string, workspaceId: string): Promise<DocumentRecord>;
  renameDocument(id: string, newId: string, workspaceId: string): Promise<DocumentRecord>;
  deleteDocument(id: string, workspaceId: string): Promise<DocumentDeleted>;
  getDocumentStatus(documentId: string, workspaceId?: string): Promise<Record<string, unknown>>;
  createDocument(input: DocumentCreateInput): Promise<Record<string, unknown>>;
  importDocument(file: File, workspace: Workspace, options?: { documentId?: string; template?: string; title?: string }): Promise<ImportResult>;
}

export function createWorkspacesApi(t: Transport): WorkspacesApi {
  const workspacePath = (id: string) => `workspaces/${encodeURIComponent(id)}`;
  const api: WorkspacesApi = {
    async listWorkspaces() {
      const items = toPage<Workspace>(await t.request<unknown>("workspaces")).items;
      const remembered = t.session.selected;
      const selected = (remembered && items.some(item => item.id === remembered) ? remembered : undefined) ?? items[0]?.id;
      if (selected) t.session.select(selected);
      const selectedItem = items.find(item => item.id === selected);
      return selectedItem ? [selectedItem, ...items.filter(item => item.id !== selected)] : items;
    },
    async createWorkspace(input) {
      const workspace = await t.request<Workspace>("workspaces", jsonInit("POST", input));
      await api.selectWorkspace(workspace.id);
      return workspace;
    },
    renameWorkspace: (id, name) => t.request(workspacePath(id), jsonInit("PATCH", { name })),
    async deleteWorkspace(id) {
      const result = await t.request<Record<string, unknown>>(workspacePath(id), jsonInit("DELETE"));
      if (t.session.selected === id) t.session.select(undefined);
      return result;
    },
    getWorkspaceStatus: id => t.request(`${workspacePath(id)}/status`),
    migrateWorkspace: (id, input) => t.request(`${workspacePath(id)}/migrate`, jsonInit("POST", input)),
    async selectWorkspace(id) {
      const workspace = await t.request<Workspace>(`${workspacePath(id)}/use`, jsonInit("POST"));
      t.session.select(id);
      return workspace;
    },
    listDocuments: async workspaceId => (await listPage<DocumentRecord>(t.scoped, "documents", { workspaceId })).items,
    getDocument: id => t.scoped(docPath(id)),
    getCurrentDocument: workspaceId => t.request(`current-document?workspace_id=${encodeURIComponent(workspaceId)}`),
    useDocument: (id, workspaceId) => t.scoped(`${docPath(id)}/use`, jsonInit("POST"), workspaceId),
    renameDocument: (id, newId, workspaceId) => t.scoped(docPath(id), jsonInit("PATCH", { new_id: newId }), workspaceId),
    deleteDocument: (id, workspaceId) => t.scoped(docPath(id), jsonInit("DELETE"), workspaceId),
    getDocumentStatus: (id, workspaceId) => t.scoped(`${docPath(id)}/status`, {}, workspaceId),
    createDocument: input => t.scoped("documents", jsonInit("POST", { workspace_id: input.workspaceId, document_id: input.documentId, template: input.template, title: input.title ?? "" }), input.workspaceId),
    async importDocument(file, workspace, options = {}) {
      const query = new URLSearchParams({ workspace_id: workspace.id, template: options.template ?? "documento-generico", title: options.title ?? file.name });
      if (options.documentId) query.set("document_id", options.documentId);
      return t.scoped<ImportResult>(`documents/import/raw?${query}`, { method: "POST", headers: { "Content-Type": file.type || "application/octet-stream", "X-Docs-Filename": file.name }, body: new Uint8Array(await file.arrayBuffer()) }, workspace.id);
    },
  };
  return api;
}
