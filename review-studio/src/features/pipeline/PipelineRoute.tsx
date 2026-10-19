import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useActiveContext, type ActiveContext } from "@/app/active-context";
import { PageHeader } from "@/components/shared/PageHeader";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";
import { PipelineLauncher } from "./PipelineLauncher";
import { RunList } from "./RunList";

function PipelineView({ header, context }: { header: ReactNode; context: ActiveContext }) {
  const { t } = useT();
  const { workspaceId, workspaceName, documentId, documentTitle } = context;
  return <div className="grid gap-6">
    {header}
    {documentId && <section aria-label={t("au.activeContext")} className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-lg border bg-card px-4 py-3 text-sm">
      <span><span className="text-muted-foreground">{t("ctx.workspace")}</span> {workspaceName}</span>
      <span><span className="text-muted-foreground">{t("au.document")}</span> {documentId}{documentTitle ? ` (${documentTitle})` : ""}</span>
      <Button asChild variant="link" className="h-auto p-0"><Link to="/authoring">{t("pl.editLink")}</Link></Button>
    </section>}
    <PipelineLauncher context={context} />
    <RunList workspaceId={workspaceId} />
  </div>;
}

export function PipelineRoute() {
  const { t } = useT();
  const active = useActiveContext();
  const header = <PageHeader eyebrow={t("pl.eyebrow")} title={t("pl.title")} description={t("pl.description")} />;
  return <QueryBoundary query={active} header={header}>{context => <PipelineView header={header} context={context} />}</QueryBoundary>;
}
