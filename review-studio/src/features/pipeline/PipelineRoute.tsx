import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useActiveContext, type ActiveContext } from "@/app/active-context";
import { PageHeader } from "@/components/shared/PageHeader";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Button } from "@/components/ui/button";
import { PipelineLauncher } from "./PipelineLauncher";
import { RunList } from "./RunList";

function PipelineView({ header, context }: { header: ReactNode; context: ActiveContext }) {
  const { workspaceId, workspaceName, documentId, documentTitle } = context;
  return <div className="grid gap-6">
    {header}
    {documentId && <section aria-label="Active context" className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-lg border bg-card px-4 py-3 text-sm">
      <span><span className="text-muted-foreground">Workspace</span> {workspaceName}</span>
      <span><span className="text-muted-foreground">Document</span> {documentId}{documentTitle ? ` (${documentTitle})` : ""}</span>
      <Button asChild variant="link" className="h-auto p-0"><Link to="/authoring">Edit sources and sections</Link></Button>
    </section>}
    <PipelineLauncher context={context} />
    <RunList workspaceId={workspaceId} />
  </div>;
}

export function PipelineRoute() {
  const active = useActiveContext();
  const header = <PageHeader eyebrow="Task area" title="Pipeline" description="Plan, launch, and watch runs for the current document." />;
  return <QueryBoundary query={active} header={header}>{context => <PipelineView header={header} context={context} />}</QueryBoundary>;
}
