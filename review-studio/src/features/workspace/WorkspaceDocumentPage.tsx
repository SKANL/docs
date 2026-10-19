import { useIsMutating, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import { PageHeader } from "@/components/shared/PageHeader";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/shared/ErrorState";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { DocumentsSection } from "./DocumentsSection";
import { WorkspaceSection } from "./WorkspaceSection";
import { refreshWorkspaceData, useWorkspaces } from "./data";

const banner = "flex items-center justify-between gap-4 rounded-md px-4 py-3 text-sm";

function isDesktopRuntime() {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** `/configure/workspaces`: choose where you work, then open or create a document. The service owns every lifecycle rule. */
export function WorkspaceDocumentPage() {
  const api = useApi();
  const { t } = useT();
  const queryClient = useQueryClient();
  const busy = useIsMutating() > 0;
  const workspaces = useWorkspaces();
  const [notice, setNotice] = useState("");
  const refresh = () => refreshWorkspaceData.forEach(queryKey => void queryClient.invalidateQueries({ queryKey }));
  const list = workspaces.data ?? [];

  return <div className="grid gap-6" aria-busy={workspaces.isFetching}>
    <PageHeader eyebrow={t("ws.page.eyebrow")} title={t("ws.page.title")} description={t("ws.page.description")} actions={<Button type="button" variant="outline" onClick={refresh} disabled={busy}>{t("common.refresh")}</Button>} />
    <p className={cn(banner, "bg-muted text-muted-foreground")} role="status">{isDesktopRuntime()
      ? t("ws.page.desktop")
      : t("ws.page.browser")}</p>
    {!api.listWorkspaces ? <ErrorState message={t("ws.page.unsupported")} />
      : workspaces.isError && <ErrorState error={workspaces.error} onRetry={refresh} retrying={busy} />}
    {notice && <p className={cn(banner, "bg-success/10 text-success")} role="status">{notice}</p>}
    {workspaces.isFetching && <div className="grid gap-2" role="status"><Skeleton className="h-4 w-1/3" /><span className="sr-only">{t("ws.page.loading")}</span></div>}
    <WorkspaceSection workspaces={list} loading={workspaces.isFetching} onNotice={setNotice} />
    <DocumentsSection workspaceId={list[0]?.id ?? null} onNotice={setNotice} />
  </div>;
}
