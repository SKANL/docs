import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import type { DocumentRecord, Template, Workspace, WorkspaceMigration, WorkspaceStatus, ReviewApi } from "../../api/models";
import { formatApiError } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "../../components/ui/alert-dialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";
import { WorkspaceFormDialog } from "./WorkspaceFormDialog";
import { WorkspaceMigrationDialog } from "./WorkspaceMigrationDialog";
import { DocumentCreateDialog } from "../documents/DocumentCreateDialog";
import { DocumentStatusPanel } from "../documents/DocumentStatusPanel";
import "./workspace.css";

type Props = { api: ReviewApi };
type BusyAction = "load" | "select" | "workspace-save" | "workspace-delete" | "migration-inspect" | "migration-apply" | "document-create" | "document-use" | "document-rename" | "document-delete" | null;
type CurrentDocument = { current_document_id: string | null; document: DocumentRecord | null };

function isDesktopRuntime() {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function WorkspaceDocumentPage({ api }: Props) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [workspaceStatus, setWorkspaceStatus] = useState<WorkspaceStatus | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [currentDocument, setCurrentDocument] = useState<CurrentDocument | null>(null);
  const [documentStatus, setDocumentStatus] = useState<Record<string, unknown> | null>(null);
  const [documentStatusError, setDocumentStatusError] = useState("");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [busy, setBusy] = useState<BusyAction>("load");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [workspaceForm, setWorkspaceForm] = useState<"create" | "rename" | null>(null);
  const [workspaceDeleteOpen, setWorkspaceDeleteOpen] = useState(false);
  const [migrationOpen, setMigrationOpen] = useState(false);
  const [migrationReport, setMigrationReport] = useState<WorkspaceMigration | null>(null);
  const [migratedName, setMigratedName] = useState("");
  const [documentCreateOpen, setDocumentCreateOpen] = useState(false);
  const [renamingDocument, setRenamingDocument] = useState<DocumentRecord | null>(null);
  const [renamedId, setRenamedId] = useState("");
  const [deletingDocument, setDeletingDocument] = useState<DocumentRecord | null>(null);

  const selectedWorkspace = useMemo(() => workspaces.find(item => item.id === selectedId) ?? null, [selectedId, workspaces]);
  const activeDocument = useMemo(() => currentDocument?.document ?? documents.find(item => item.id === currentDocument?.current_document_id) ?? null, [currentDocument, documents]);

  const refreshWorkspaceData = useCallback(async (id: string) => {
    const [nextDocuments, nextCurrent, nextStatus] = await Promise.all([
      api.listDocuments?.(id) ?? Promise.resolve([]),
      api.getCurrentDocument?.(id) ?? Promise.resolve({ current_document_id: null, document: null }),
      api.getWorkspaceStatus?.(id) ?? Promise.resolve(null),
    ]);
    setDocuments(nextDocuments);
    setCurrentDocument(nextCurrent);
    setWorkspaceStatus(nextStatus);
    if (nextCurrent.current_document_id && api.getDocumentStatus) {
      try {
        setDocumentStatus(await api.getDocumentStatus(nextCurrent.current_document_id, id));
        setDocumentStatusError("");
      } catch (cause) {
        setDocumentStatus(null);
        setDocumentStatusError(formatApiError(cause, "document status"));
      }
    } else { setDocumentStatus(null); setDocumentStatusError(""); }
  }, [api]);

  const refresh = useCallback(async (preferredId?: string) => {
    if (!api.listWorkspaces) { setError("Workspace operations are not available from this API."); setBusy(null); return; }
    setBusy("load");
    setError("");
    try {
      const nextWorkspaces = await api.listWorkspaces();
      setWorkspaces(nextWorkspaces);
      const selected = preferredId && nextWorkspaces.some(item => item.id === preferredId) ? preferredId : nextWorkspaces[0]?.id ?? "";
      setSelectedId(selected);
      if (selected) {
        setTemplates(await api.listTemplates());
        await refreshWorkspaceData(selected);
      }
      else {
        setTemplates([]);
        setWorkspaceStatus(null);
        setDocuments([]);
        setCurrentDocument(null);
        setDocumentStatus(null);
        setDocumentStatusError("");
      }
    } catch (cause) {
      setError(formatApiError(cause, "workspace data"));
    } finally { setBusy(null); }
  }, [api, refreshWorkspaceData]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function runAction(action: Exclude<BusyAction, "load" | "select" | null>, task: () => Promise<void>, resource: string) {
    setBusy(action);
    setError("");
    setNotice("");
    try { await task(); }
    catch (cause) { setError(formatApiError(cause, resource)); }
    finally { setBusy(null); }
  }

  async function selectWorkspace(id: string) {
    if (!id || id === selectedId || !api.selectWorkspace) return;
    setBusy("select"); setError(""); setNotice("");
    try { await api.selectWorkspace(id); setSelectedId(id); await refreshWorkspaceData(id); }
    catch (cause) { setError(formatApiError(cause, "workspace")); }
    finally { setBusy(null); }
  }

  async function retryDocumentStatus() {
    const documentId = currentDocument?.current_document_id;
    if (!documentId || !selectedId || !api.getDocumentStatus || busy) return;
    setBusy("load");
    try {
      setDocumentStatus(await api.getDocumentStatus(documentId, selectedId));
      setDocumentStatusError("");
    } catch (cause) { setDocumentStatusError(formatApiError(cause, "document status")); }
    finally { setBusy(null); }
  }

  async function saveWorkspace(name: string) {
    if (workspaceForm === "create" && api.createWorkspace) {
      await runAction("workspace-save", async () => {
        const created = await api.createWorkspace!({ name });
        setWorkspaceForm(null);
        setNotice(`Workspace ${created.name} created.`);
        await refresh(created.id);
      }, "workspace");
    } else if (workspaceForm === "rename" && selectedWorkspace && api.renameWorkspace) {
      await runAction("workspace-save", async () => {
        const renamed = await api.renameWorkspace!(selectedWorkspace.id, name);
        setWorkspaces(items => items.map(item => item.id === renamed.id ? renamed : item));
        setWorkspaceStatus(current => current ? { ...current, workspace: renamed } : current);
        setWorkspaceForm(null);
        setNotice("Workspace name updated.");
      }, "workspace");
    }
  }

  async function deleteWorkspace() {
    if (!selectedWorkspace || !api.deleteWorkspace) return;
    await runAction("workspace-delete", async () => {
      await api.deleteWorkspace!(selectedWorkspace.id);
      const remaining = workspaces.filter(item => item.id !== selectedWorkspace.id);
      setWorkspaceDeleteOpen(false);
      setWorkspaces(remaining);
      setNotice("Workspace deleted.");
      if (remaining[0] && api.selectWorkspace) {
        await api.selectWorkspace(remaining[0].id);
        await refresh(remaining[0].id);
      } else {
        setSelectedId(""); setWorkspaceStatus(null); setDocuments([]); setCurrentDocument(null); setDocumentStatus(null);
      }
    }, "workspace");
  }

  async function inspectMigration() {
    if (!selectedWorkspace || !api.migrateWorkspace) return;
    setBusy("migration-inspect"); setError(""); setMigrationReport(null); setMigratedName("");
    try { setMigrationReport(await api.migrateWorkspace(selectedWorkspace.id, { apply: false })); }
    catch (cause) { setError(formatApiError(cause, "workspace migration")); }
    finally { setBusy(null); }
  }

  async function applyMigration() {
    if (!selectedWorkspace || !api.migrateWorkspace || !migrationReport?.ready) return;
    setBusy("migration-apply"); setError("");
    try {
      const result = await api.migrateWorkspace(selectedWorkspace.id, { apply: true });
      if (result.workspace) {
        setMigratedName(result.workspace.name);
        await api.selectWorkspace?.(result.workspace.id);
        await refresh(result.workspace.id);
      } else {
        setMigrationReport(null);
        setError("Migration response did not include the resulting workspace. Inspect the source again before retrying.");
      }
    } catch (cause) { setError(formatApiError(cause, "workspace migration")); }
    finally { setBusy(null); }
  }

  async function createDocument(input: { documentId: string; title: string; template: string }) {
    if (!selectedId || !api.createDocument) return;
    await runAction("document-create", async () => {
      await api.createDocument!({ workspaceId: selectedId, documentId: input.documentId, title: input.title, template: input.template });
      setDocumentCreateOpen(false);
      await refreshWorkspaceData(selectedId);
      if (!api.useDocument) {
        setNotice(`Document ${input.title} created, but selection is unavailable in this API.`);
        return;
      }
      try {
        await api.useDocument(input.documentId, selectedId);
        await refreshWorkspaceData(selectedId);
        setNotice(`Document ${input.title} created and selected.`);
      } catch (cause) {
        setNotice(`Document ${input.title} was created, but could not be selected.`);
        setError(formatApiError(cause, "document selection"));
      }
    }, "document");
  }

  async function selectDocument(documentId: string) {
    if (!selectedId || !api.useDocument) return;
    await runAction("document-use", async () => { await api.useDocument!(documentId, selectedId); await refreshWorkspaceData(selectedId); setNotice(`Document ${documentId} selected.`); }, "document");
  }

  async function saveDocumentName(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedId || !renamingDocument || !api.renameDocument) return;
    await runAction("document-rename", async () => {
      const result = await api.renameDocument!(renamingDocument.id, renamedId.trim(), selectedId);
      setRenamingDocument(null); setRenamedId("");
      await refreshWorkspaceData(selectedId);
      if (currentDocument?.current_document_id === renamingDocument.id) setCurrentDocument({ current_document_id: result.id, document: result });
      setNotice(`Document renamed to ${result.id}.`);
    }, "document");
  }

  async function deleteDocument() {
    if (!selectedId || !deletingDocument || !api.deleteDocument) return;
    await runAction("document-delete", async () => {
      const result = await api.deleteDocument!(deletingDocument.id, selectedId);
      setDeletingDocument(null);
      await refreshWorkspaceData(selectedId);
      if (!result.current_document_id) { setCurrentDocument({ current_document_id: null, document: null }); setDocumentStatus(null); }
      setNotice(`Document ${result.deleted} deleted.`);
    }, "document");
  }

  const isBusy = busy !== null;
  return <div className="ws-page" aria-busy={busy === "load"}>
    <header className="ws-page-header"><div><p className="ws-kicker">Workspace setup</p><h1>Workspace and document control</h1><p className="ws-lede">Choose where you work, then open or create a document. The service owns all lifecycle rules.</p></div><Button type="button" variant="outline" onClick={() => void refresh(selectedId)} disabled={isBusy}>Refresh</Button></header>
    {isDesktopRuntime() ? <p className="ws-platform-note" role="status">Desktop storage is prepared in app data before the local service starts. This screen uses the same workspace and document operations as the browser.</p> : <p className="ws-platform-note" role="status">Workspace storage is managed by the connected Review API. Your browser remembers the selected workspace on this device.</p>}
    {error && <div className="ws-page-alert" role="alert"><span>{error}</span><Button type="button" variant="outline" onClick={() => void refresh(selectedId)} disabled={isBusy}>Try again</Button></div>}
    {notice && <p className="ws-page-notice" role="status">{notice}</p>}
    {busy === "load" && <div className="ws-loading" role="status">Loading workspace and document data…</div>}
    <section className="ws-context-section" aria-labelledby="workspace-heading">
      <div className="ws-section-heading"><div><p className="ws-kicker">Operating context</p><h2 id="workspace-heading">Workspace</h2></div>{selectedWorkspace && <span className="ws-active-marker">{workspaceStatus?.active ? "Active on service" : "Selected on this device"}</span>}</div>
        {workspaces.length > 0 ? <>
        <WorkspaceSwitcher workspaces={workspaces} selectedId={selectedId} busy={isBusy} canCreate={Boolean(api.createWorkspace)} canSelect={Boolean(api.selectWorkspace)} onSelect={id => void selectWorkspace(id)} onCreate={() => setWorkspaceForm("create")} />
        {selectedWorkspace && <div className="ws-workspace-meta"><div><span className="ws-status-label">Storage location</span><code>{selectedWorkspace.root}</code></div><div className="ws-management-actions">
          <Button type="button" variant="ghost" onClick={() => setWorkspaceForm("rename")} disabled={isBusy || !api.renameWorkspace}>Rename workspace</Button>
          <Button type="button" variant="outline" onClick={() => { setMigrationReport(null); setMigratedName(""); setMigrationOpen(true); }} disabled={isBusy || !api.migrateWorkspace}>Review migration</Button>
          <Button type="button" variant="destructive" onClick={() => setWorkspaceDeleteOpen(true)} disabled={isBusy || !api.deleteWorkspace}>Delete workspace</Button>
        </div></div>}
      </> : busy !== "load" && <div className="ws-empty-workspace"><h3>No workspace yet</h3><p>Create one to initialize its storage and start a document. In desktop mode, the local service stores managed workspaces under the app-data workspace.</p><Button type="button" onClick={() => setWorkspaceForm("create")} disabled={!api.createWorkspace}>Create workspace</Button></div>}
    </section>

    <section className="ws-context-section" aria-labelledby="documents-heading">
      <div className="ws-section-heading"><div><p className="ws-kicker">Current project</p><h2 id="documents-heading">Documents</h2></div><Button type="button" onClick={() => setDocumentCreateOpen(true)} disabled={!selectedWorkspace || isBusy || !api.createDocument}>Create document</Button></div>
      {!selectedWorkspace ? <p className="ws-muted">Select or create a workspace before managing documents.</p> : <>
        <DocumentStatusPanel document={activeDocument} status={documentStatus} loading={busy === "select" || busy === "load"} error={documentStatusError || undefined} onRetry={() => void retryDocumentStatus()} />
        {documents.length ? <ul className="ws-document-list" aria-label="Workspace documents">{documents.map(item => <li key={item.id} className={item.id === currentDocument?.current_document_id ? "is-current" : ""}>
          <div className="ws-document-copy"><strong>{item.title || item.id}</strong><span>{item.id}{item.template ? ` · ${item.template}` : ""}</span></div>
          <div className="ws-document-actions"><Button type="button" variant={item.id === currentDocument?.current_document_id ? "secondary" : "ghost"} onClick={() => void selectDocument(item.id)} disabled={isBusy || !api.useDocument}>{item.id === currentDocument?.current_document_id ? "Current" : `Use ${item.id}`}</Button>
            <Button type="button" variant="ghost" aria-label={`Rename ${item.id}`} onClick={() => { setRenamingDocument(item); setRenamedId(item.id); }} disabled={isBusy || !api.renameDocument}>Rename</Button>
            <Button type="button" variant="ghost" aria-label={`Delete ${item.id}`} onClick={() => setDeletingDocument(item)} disabled={isBusy || !api.deleteDocument}>Delete</Button></div>
        </li>)}</ul> : <p className="ws-empty-documents" role="status">No documents yet. Create a document to begin.</p>}
      </>}
    </section>

    <WorkspaceFormDialog mode={workspaceForm ?? "create"} workspace={selectedWorkspace ?? undefined} open={workspaceForm !== null} pending={busy === "workspace-save"} error={error || undefined} onOpenChange={open => { if (!open) { setWorkspaceForm(null); setError(""); } }} onSubmit={name => void saveWorkspace(name)} />
    <WorkspaceMigrationDialog workspace={selectedWorkspace ?? { id: "", name: "", root: "" }} open={migrationOpen && Boolean(selectedWorkspace)} pending={busy === "migration-inspect" || busy === "migration-apply"} report={migrationReport} error={error || undefined} migratedName={migratedName} onOpenChange={setMigrationOpen} onInspect={() => void inspectMigration()} onMigrate={() => void applyMigration()} />
    <DocumentCreateDialog open={documentCreateOpen} pending={busy === "document-create"} templates={templates} error={error || undefined} onOpenChange={open => { if (!open) { setDocumentCreateOpen(false); setError(""); } }} onSubmit={input => void createDocument(input)} />
    <Dialog open={Boolean(renamingDocument)} onOpenChange={open => { if (!open) setRenamingDocument(null); }}>
      <DialogContent aria-describedby="document-rename-description"><DialogHeader><DialogTitle>Rename document</DialogTitle><DialogDescription id="document-rename-description">The service updates the document identifier and its managed files.</DialogDescription></DialogHeader>
        <form onSubmit={event => void saveDocumentName(event)}><label className="field-label" htmlFor="document-new-id">New document ID</label><Input id="document-new-id" required value={renamedId} onChange={event => setRenamedId(event.target.value)} />{error && <p className="inline-error" role="alert">{error}</p>}<DialogFooter><Button type="button" variant="ghost" onClick={() => setRenamingDocument(null)} disabled={busy === "document-rename"}>Cancel</Button><Button type="submit" disabled={busy === "document-rename" || !renamedId.trim()}>Save name</Button></DialogFooter></form>
      </DialogContent>
    </Dialog>
    <AlertDialog open={workspaceDeleteOpen} onOpenChange={setWorkspaceDeleteOpen}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Delete workspace</AlertDialogTitle><AlertDialogDescription>This removes the workspace from the registry. Its files are not deleted. You cannot undo this registry change.</AlertDialogDescription></AlertDialogHeader>{error && <p className="inline-error" role="alert">{error}</p>}<AlertDialogFooter><AlertDialogCancel asChild><Button type="button" variant="ghost" disabled={busy === "workspace-delete"}>Cancel</Button></AlertDialogCancel><AlertDialogAction asChild><Button type="button" variant="destructive" disabled={busy === "workspace-delete"} onClick={event => { event.preventDefault(); void deleteWorkspace(); }}>Delete workspace</Button></AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
    <AlertDialog open={Boolean(deletingDocument)} onOpenChange={open => { if (!open) setDeletingDocument(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Delete document</AlertDialogTitle><AlertDialogDescription>This permanently removes {deletingDocument?.id ?? "the document"} and its managed files from the selected workspace.</AlertDialogDescription></AlertDialogHeader>{error && <p className="inline-error" role="alert">{error}</p>}<AlertDialogFooter><AlertDialogCancel asChild><Button type="button" variant="ghost" disabled={busy === "document-delete"}>Cancel</Button></AlertDialogCancel><AlertDialogAction asChild><Button type="button" variant="destructive" disabled={busy === "document-delete"} onClick={event => { event.preventDefault(); void deleteDocument(); }}>Delete document</Button></AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </div>;
}
