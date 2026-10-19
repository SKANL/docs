import { useIsMutating, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import type { DocumentRecord } from "@/api/models";
import { useActiveContext } from "@/app/active-context";
import { useApi } from "@/app/providers";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { EmptyState } from "@/components/shared/EmptyState";
import { useT } from "@/lib/i18n";
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
  const { t } = useT();
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
  const [selectionError, setSelectionError] = useState<unknown>(null);
  const common = { notify: onNotice, invalidate: refreshWorkspaceData };

  const create = useAction(async (input: { documentId: string; title: string; template: string }) => {
    setSelectionError(null);
    await api.createDocument!({ workspaceId: workspaceId!, ...input });
    if (!api.useDocument) return t("doc.created.noSelect", { title: input.title });
    try {
      await api.useDocument(input.documentId, workspaceId!);
      return t("doc.created.selected", { title: input.title });
    } catch (cause) {
      setSelectionError(cause);
      return t("doc.created.selectFailed", { title: input.title });
    }
  }, { ...common, success: message => message, onDone: () => setCreateOpen(false) });
  const select = useAction((id: string) => api.useDocument!(id, workspaceId!), { ...common, success: (_result, id) => t("doc.selected", { id }) });
  const rename = useAction((input: { id: string; newId: string }) => api.renameDocument!(input.id, input.newId, workspaceId!), {
    ...common, success: result => t("doc.renamed", { id: result.id }), onDone: () => { setRenaming(null); setRenamedId(""); },
  });
  const remove = useAction((id: string) => api.deleteDocument!(id, workspaceId!), { ...common, success: result => t("doc.deleted", { id: result.deleted }), onDone: () => setDeleting(null) });

  const dismissable = (action: { isError: boolean; reset(): void }, close: () => void) => () => { close(); if (action.isError) action.reset(); };
  function saveName(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (renaming) rename.mutate({ id: renaming.id, newId: renamedId.trim() });
  }

  return <section className={sectionClass} aria-labelledby="documents-heading">
    <div className="flex items-center justify-between gap-4"><div><p className={kickerClass}>{t("doc.kicker")}</p><h2 id="documents-heading" className="text-xl font-semibold">{t("doc.heading")}</h2></div><Button type="button" onClick={() => setCreateOpen(true)} disabled={!workspaceId || busy || !api.createDocument}>{t("doc.create")}</Button></div>
    {!workspaceId ? <p className="text-sm text-muted-foreground">{t("doc.selectWorkspaceFirst")}</p> : <>
      {currentId && <DocumentDetailPanel documentId={currentId} />}
      <DocumentStatusPanel document={current} status={status.data ?? null} loading={status.isPending && status.fetchStatus !== "idle"} error={status.isError ? status.error : undefined} onRetry={() => void status.refetch()} />
      {select.isError && <ErrorState error={select.error} />}
      {selectionError != null && <ErrorState error={selectionError} />}
      {documents.isError ? <ErrorState error={documents.error} onRetry={() => void documents.refetch()} />
        : list.length ? <ul className="grid gap-1" aria-label={t("doc.listLabel")}>{list.map(item => <li key={item.id} className={cn("flex flex-col gap-3 rounded-md border-b px-2 py-3 sm:flex-row sm:items-center sm:justify-between", item.id === currentId && "border-transparent bg-muted")}>
          <div className="grid min-w-0 gap-1"><strong>{item.title || item.id}</strong><span className="text-sm break-words text-muted-foreground">{item.id}{item.template ? ` · ${item.template}` : ""}</span></div>
          <div className="flex flex-wrap gap-1.5 sm:justify-end"><Button type="button" variant={item.id === currentId ? "secondary" : "ghost"} onClick={() => select.mutate(item.id)} disabled={busy || !api.useDocument}>{item.id === currentId ? t("doc.current") : t("doc.use", { id: item.id })}</Button>
            <Button type="button" variant="ghost" aria-label={t("doc.renameLabel", { id: item.id })} onClick={() => { setRenaming(item); setRenamedId(item.id); }} disabled={busy || !api.renameDocument}>{t("doc.rename")}</Button>
            <Button type="button" variant="ghost" aria-label={t("doc.deleteLabel", { id: item.id })} onClick={() => setDeleting(item)} disabled={busy || !api.deleteDocument}>{t("doc.delete")}</Button></div>
        </li>)}</ul> : !documents.isPending && <EmptyState title={t("doc.none.title")} description={t("doc.none.body")} action={{ label: t("empty.createDocument"), onClick: () => setCreateOpen(true) }} />}
    </>}

    <DocumentCreateDialog open={createOpen} pending={create.isPending} templates={templates.data ?? []} error={create.error} onOpenChange={open => { if (!open) dismissable(create, () => setCreateOpen(false))(); }} onSubmit={input => create.mutate(input)} />
    <Dialog open={Boolean(renaming)} onOpenChange={open => { if (!open) dismissable(rename, () => setRenaming(null))(); }}>
      <DialogContent showCloseButton={false} aria-describedby="document-rename-description"><DialogHeader><DialogTitle>{t("doc.renameTitle")}</DialogTitle><DialogDescription id="document-rename-description">{t("doc.renameBody")}</DialogDescription></DialogHeader>
        <form onSubmit={saveName} className="grid gap-4"><div className="grid gap-2"><Label htmlFor="document-new-id">{t("doc.newId")}</Label><Input id="document-new-id" required value={renamedId} onChange={event => setRenamedId(event.target.value)} /></div>{rename.isError && <ErrorState error={rename.error} />}<DialogFooter><Button type="button" variant="ghost" onClick={() => setRenaming(null)} disabled={rename.isPending}>{t("common.cancel")}</Button><Button type="submit" disabled={rename.isPending || !renamedId.trim()}>{t("doc.saveName")}</Button></DialogFooter></form>
      </DialogContent>
    </Dialog>
    <ConfirmActionDialog open={Boolean(deleting)} onOpenChange={open => { if (!open) dismissable(remove, () => setDeleting(null))(); }} title={t("doc.deleteTitle")} description={t("doc.deleteBody", { id: deleting?.id ?? t("doc.deleteBodyUnnamed") })} confirmLabel={t("doc.deleteTitle")} pending={remove.isPending} error={remove.error} onConfirm={() => remove.mutate(deleting!.id)} />
  </section>;
}
