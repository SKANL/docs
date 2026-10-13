import { useIsMutating, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { formatApiError } from "@/api/errors";
import type { DocumentRecord } from "@/api/models";
import { useActiveContext } from "@/app/active-context";
import { useApi } from "@/app/providers";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { ErrorState } from "@/components/shared/ErrorState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAction } from "@/lib/actions";
import { cn } from "@/lib/utils";
import { DocumentCreateDialog } from "../documents/DocumentCreateDialog";
import { DocumentDetailPanel } from "../documents/DocumentDetailPanel";
import { DocumentStatusPanel } from "../documents/DocumentStatusPanel";
import { kickerClass, refreshWorkspaceData, sectionClass, workspaceKeys } from "./data";

type Props = { workspaceId: string | null; onNotice(message: string): void };

/** The selected workspace's documents, the current one's readiness, and the operations on them. */
export function DocumentsSection({ workspaceId, onNotice }: Props) {
  const api = useApi();
  const busy = useIsMutating() > 0;
  const active = useActiveContext();
  const currentId = active.data?.documentId ?? null;
  const scope = workspaceId ?? "";
  const documents = useQuery({ queryKey: workspaceKeys.documents(scope), queryFn: () => api.listDocuments!(scope), enabled: !!workspaceId && !!api.listDocuments });
  const templates = useQuery({ queryKey: workspaceKeys.templates(scope), queryFn: () => api.listTemplates(), enabled: !!workspaceId });
  const status = useQuery({ queryKey: workspaceKeys.documentStatus(scope, currentId ?? ""), queryFn: () => api.getDocumentStatus!(currentId!, scope), enabled: !!workspaceId && !!currentId && !!api.getDocumentStatus });
  const list = documents.data ?? [];
  const current = list.find(item => item.id === currentId) ?? (currentId ? { id: currentId, title: active.data?.documentTitle ?? undefined } : null);

  const [createOpen, setCreateOpen] = useState(false);
  const [renaming, setRenaming] = useState<DocumentRecord | null>(null);
  const [renamedId, setRenamedId] = useState("");
  const [deleting, setDeleting] = useState<DocumentRecord | null>(null);
  const [selectionError, setSelectionError] = useState("");
  const common = { notify: onNotice, invalidate: refreshWorkspaceData };

  const create = useAction(async (input: { documentId: string; title: string; template: string }) => {
    setSelectionError("");
    await api.createDocument!({ workspaceId: workspaceId!, ...input });
    if (!api.useDocument) return `Document ${input.title} created, but selection is unavailable in this API.`;
    try {
      await api.useDocument(input.documentId, workspaceId!);
      return `Document ${input.title} created and selected.`;
    } catch (cause) {
      setSelectionError(formatApiError(cause));
      return `Document ${input.title} was created, but could not be selected.`;
    }
  }, { ...common, success: message => message, onDone: () => setCreateOpen(false) });
  const select = useAction((id: string) => api.useDocument!(id, workspaceId!), { ...common, success: (_result, id) => `Document ${id} selected.` });
  const rename = useAction((input: { id: string; newId: string }) => api.renameDocument!(input.id, input.newId, workspaceId!), {
    ...common, success: result => `Document renamed to ${result.id}.`, onDone: () => { setRenaming(null); setRenamedId(""); },
  });
  const remove = useAction((id: string) => api.deleteDocument!(id, workspaceId!), { ...common, success: result => `Document ${result.deleted} deleted.`, onDone: () => setDeleting(null) });

  const dismissable = (action: { isError: boolean; reset(): void }, close: () => void) => () => { close(); if (action.isError) action.reset(); };
  function saveName(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (renaming) rename.mutate({ id: renaming.id, newId: renamedId.trim() });
  }

  return <section className={sectionClass} aria-labelledby="documents-heading">
    <div className="flex items-center justify-between gap-4"><div><p className={kickerClass}>Current project</p><h2 id="documents-heading" className="text-xl font-semibold">Documents</h2></div><Button type="button" onClick={() => setCreateOpen(true)} disabled={!workspaceId || busy || !api.createDocument}>Create document</Button></div>
    {!workspaceId ? <p className="text-sm text-muted-foreground">Select or create a workspace before managing documents.</p> : <>
      {currentId && <DocumentDetailPanel documentId={currentId} />}
      <DocumentStatusPanel document={current} status={status.data ?? null} loading={status.isPending && status.fetchStatus !== "idle"} error={status.isError ? formatApiError(status.error, "document status") : undefined} onRetry={() => void status.refetch()} />
      {select.isError && <ErrorState message={formatApiError(select.error)} />}
      {selectionError && <ErrorState message={selectionError} />}
      {documents.isError ? <ErrorState message={formatApiError(documents.error, "documents")} onRetry={() => void documents.refetch()} />
        : list.length ? <ul className="grid gap-1" aria-label="Workspace documents">{list.map(item => <li key={item.id} className={cn("flex flex-col gap-3 rounded-md border-b px-2 py-3 sm:flex-row sm:items-center sm:justify-between", item.id === currentId && "border-transparent bg-muted")}>
          <div className="grid min-w-0 gap-1"><strong>{item.title || item.id}</strong><span className="text-sm break-words text-muted-foreground">{item.id}{item.template ? ` · ${item.template}` : ""}</span></div>
          <div className="flex flex-wrap gap-1.5 sm:justify-end"><Button type="button" variant={item.id === currentId ? "secondary" : "ghost"} onClick={() => select.mutate(item.id)} disabled={busy || !api.useDocument}>{item.id === currentId ? "Current" : `Use ${item.id}`}</Button>
            <Button type="button" variant="ghost" aria-label={`Rename ${item.id}`} onClick={() => { setRenaming(item); setRenamedId(item.id); }} disabled={busy || !api.renameDocument}>Rename</Button>
            <Button type="button" variant="ghost" aria-label={`Delete ${item.id}`} onClick={() => setDeleting(item)} disabled={busy || !api.deleteDocument}>Delete</Button></div>
        </li>)}</ul> : !documents.isPending && <p className="py-3 text-sm text-muted-foreground" role="status">No documents yet. Create a document to begin.</p>}
    </>}

    <DocumentCreateDialog open={createOpen} pending={create.isPending} templates={templates.data ?? []} error={create.isError ? formatApiError(create.error) : undefined} onOpenChange={open => { if (!open) dismissable(create, () => setCreateOpen(false))(); }} onSubmit={input => create.mutate(input)} />
    <Dialog open={Boolean(renaming)} onOpenChange={open => { if (!open) dismissable(rename, () => setRenaming(null))(); }}>
      <DialogContent showCloseButton={false} aria-describedby="document-rename-description"><DialogHeader><DialogTitle>Rename document</DialogTitle><DialogDescription id="document-rename-description">The service updates the document identifier and its managed files.</DialogDescription></DialogHeader>
        <form onSubmit={saveName} className="grid gap-4"><div className="grid gap-2"><Label htmlFor="document-new-id">New document ID</Label><Input id="document-new-id" required value={renamedId} onChange={event => setRenamedId(event.target.value)} /></div>{rename.isError && <p className="text-sm text-destructive" role="alert">{formatApiError(rename.error)}</p>}<DialogFooter><Button type="button" variant="ghost" onClick={() => setRenaming(null)} disabled={rename.isPending}>Cancel</Button><Button type="submit" disabled={rename.isPending || !renamedId.trim()}>Save name</Button></DialogFooter></form>
      </DialogContent>
    </Dialog>
    <ConfirmActionDialog open={Boolean(deleting)} onOpenChange={open => { if (!open) dismissable(remove, () => setDeleting(null))(); }} title="Delete document" description={`This permanently removes ${deleting?.id ?? "the document"} and its managed files from the selected workspace.`} confirmLabel="Delete document" pending={remove.isPending} error={remove.isError ? formatApiError(remove.error) : undefined} onConfirm={() => remove.mutate(deleting!.id)} />
  </section>;
}
