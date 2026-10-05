import { Link } from "react-router-dom";
import { ErrorState } from "@/components/shared/ErrorState";
import { PageHeader } from "@/components/shared/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorText, useActiveContext } from "@/features/authoring/data";
import { PipelineLauncher } from "./PipelineLauncher";
import { RunList } from "./RunList";

export function PipelineRoute() {
  const active = useActiveContext();
  const header = <PageHeader eyebrow="Task area" title="Pipeline" description="Plan, launch, and watch runs for the current document." />;
  if (active.isPending) return <div className="grid gap-6">{header}<Skeleton className="h-24 w-full" /></div>;
  if (active.isError) return <div className="grid gap-6">{header}<ErrorState message={errorText(active.error, "workspace")} onRetry={() => void active.refetch()} /></div>;
  const { workspaceId, workspaceName, documentId, documentTitle } = active.data;
  return <div className="grid gap-6">
    {header}
    {documentId && <section aria-label="Active context" className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-lg border bg-card px-4 py-3 text-sm">
      <span><span className="text-muted-foreground">Workspace</span> {workspaceName}</span>
      <span><span className="text-muted-foreground">Document</span> {documentId}{documentTitle ? ` (${documentTitle})` : ""}</span>
      <Button asChild variant="link" className="h-auto p-0"><Link to="/authoring">Edit sources and sections</Link></Button>
    </section>}
    <PipelineLauncher context={active.data} />
    <RunList workspaceId={workspaceId} />
  </div>;
}
