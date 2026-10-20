import { useQuery } from "@tanstack/react-query";
import { useActiveContext } from "@/app/active-context";
import { useApi } from "@/app/providers";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAction } from "@/lib/actions";
import { errorMessageKey } from "@/lib/friendly-error";
import { useT } from "@/lib/i18n";
import { refreshWorkspaceData, useWorkspaces, workspaceKeys } from "./data";

/** Workspace + document pickers for the topbar. Same queries, cache keys and API calls as the Configure screens. */
export function ContextSwitcher() {
  const api = useApi();
  const { t } = useT();
  const workspaces = useWorkspaces();
  const active = useActiveContext();
  const list = workspaces.data ?? [];
  // listWorkspaces (api/domains/workspaces.ts) returns the selected workspace first; client.test.ts pins that order.
  const workspaceId = list[0]?.id ?? "";
  const documentId = active.data?.documentId ?? "";
  const documents = useQuery({ queryKey: workspaceKeys.documents(workspaceId), queryFn: () => api.listDocuments!(workspaceId), enabled: !!workspaceId && !!api.listDocuments });
  const docs = documents.data ?? [];
  const common = { invalidate: refreshWorkspaceData };
  const selectWorkspace = useAction((id: string) => api.selectWorkspace!(id), common);
  const selectDocument = useAction((id: string) => api.useDocument!(id, workspaceId), common);
  const failure = selectWorkspace.error ?? selectDocument.error;
  // A failed fetch must not read as "no workspace": say what failed.
  const loadFailure = workspaces.error ?? active.error ?? documents.error;

  return <div className="flex flex-wrap items-center gap-2">
    <Select value={workspaceId} onValueChange={id => { if (id !== workspaceId) selectWorkspace.mutate(id); }} disabled={!api.selectWorkspace || list.length === 0 || selectWorkspace.isPending}>
      <SelectTrigger size="sm" aria-label={t("ctx.workspace")} className="w-40"><SelectValue placeholder={t("ctx.noWorkspace")} /></SelectTrigger>
      <SelectContent>{list.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent>
    </Select>
    <Select value={documentId} onValueChange={id => { if (id !== documentId) selectDocument.mutate(id); }} disabled={!api.useDocument || docs.length === 0 || selectDocument.isPending}>
      <SelectTrigger size="sm" aria-label={t("ctx.document")} className="w-44"><SelectValue placeholder={workspaceId ? t("ctx.noDocument") : t("ctx.choose")} /></SelectTrigger>
      <SelectContent>{docs.map(item => <SelectItem key={item.id} value={item.id}>{item.title || item.id}</SelectItem>)}</SelectContent>
    </Select>
    {failure && <span role="alert" className="text-xs text-destructive">{t("ctx.switchFailed", { message: t(errorMessageKey(failure)) })}</span>}
    {!failure && loadFailure != null && <span role="alert" className="text-xs text-destructive">{t("ctx.loadFailed", { message: t(errorMessageKey(loadFailure)) })}</span>}
  </div>;
}
