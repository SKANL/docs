import { useIsMutating, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { formatApiError } from "@/api/errors";
import { useApi } from "@/app/providers";
import { PageHeader } from "@/components/shared/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
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
  const queryClient = useQueryClient();
  const busy = useIsMutating() > 0;
  const workspaces = useWorkspaces();
  const [notice, setNotice] = useState("");
  const refresh = () => refreshWorkspaceData.forEach(queryKey => void queryClient.invalidateQueries({ queryKey }));
  const error = !api.listWorkspaces ? "Workspace operations are not available from this API." : workspaces.isError ? formatApiError(workspaces.error, "workspace data") : "";
  const list = workspaces.data ?? [];

  return <div className="grid gap-6" aria-busy={workspaces.isFetching}>
    <PageHeader eyebrow="Workspace setup" title="Workspace and document control" description="Choose where you work, then open or create a document. The service owns all lifecycle rules." actions={<Button type="button" variant="outline" onClick={refresh} disabled={busy}>Refresh</Button>} />
    <p className={cn(banner, "bg-muted text-muted-foreground")} role="status">{isDesktopRuntime()
      ? "Desktop storage is prepared in app data before the local service starts. This screen uses the same workspace and document operations as the browser."
      : "Workspace storage is managed by the connected Review API. Your browser remembers the selected workspace on this device."}</p>
    {error && <div className={cn(banner, "border border-destructive/40 bg-destructive/10 text-destructive")} role="alert"><span>{error}</span><Button type="button" variant="outline" onClick={refresh} disabled={busy}>Try again</Button></div>}
    {notice && <p className={cn(banner, "bg-success/10 text-success")} role="status">{notice}</p>}
    {workspaces.isFetching && <div className="grid gap-2" role="status"><Skeleton className="h-4 w-1/3" /><span className="sr-only">Loading workspace and document data…</span></div>}
    <WorkspaceSection workspaces={list} loading={workspaces.isFetching} onNotice={setNotice} />
    <DocumentsSection workspaceId={list[0]?.id ?? null} onNotice={setNotice} />
  </div>;
}
