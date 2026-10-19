import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { EmptyState } from "@/components/shared/EmptyState";
import { PageHeader } from "@/components/shared/PageHeader";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AssetsPanel } from "./AssetsPanel";
import { ClassificationPanel } from "./ClassificationPanel";
import { ContextPanel } from "./ContextPanel";
import { RevisionsPanel } from "./RevisionsPanel";
import { SectionsPanel } from "./SectionsPanel";
import { SourcesPanel } from "./SourcesPanel";
import { useActiveContext, type ActiveContext } from "@/app/active-context";
import { useT } from "@/lib/i18n";
import { useClassification, useContextStatus, useSections } from "./data";

const tabs = ["sources", "classification", "assets", "context", "sections", "revisions"] as const;

/** One hint, derived only from which server data exists. It states no validity rule. */
function NextAction({ documentId }: { documentId: string }) {
  const { t } = useT();
  const sections = useSections(documentId);
  const classification = useClassification(documentId);
  const context = useContextStatus(documentId);
  const pending = classification.data?.filter(item => !item.confirmed_role).length ?? 0;
  const missing = context.data?.topics.filter(topic => topic.missing).map(topic => topic.title) ?? [];
  const hint: [string, string] | null = sections.data === undefined ? null
    : sections.data.length === 0 && !classification.data?.length ? [t("au.next.addSources"), "sources"]
    : pending > 0 ? [t(pending === 1 ? "au.next.confirmRoles.one" : "au.next.confirmRoles.other", { count: pending }), "classification"]
    : missing.length > 0 ? [t("au.next.fillContext", { topics: missing.join(", ") }), "context"]
    : sections.data.length > 0 ? [t("au.next.reviewSections"), "sections"] : null;
  if (!hint) return null;
  return <p role="status" className="text-sm">{t("au.next")} <Button asChild variant="link" className="h-auto p-0"><Link to={`/authoring/${hint[1]}`}>{hint[0]}</Link></Button></p>;
}

function AuthoringView({ header, context }: { header: ReactNode; context: ActiveContext }) {
  const { t } = useT();
  const { tab = "sources" } = useParams();
  const navigate = useNavigate();
  const { workspaceName, documentId, documentTitle } = context;
  if (!documentId) return <div className="grid gap-6">{header}
    <EmptyState title={t("au.selectDoc.title")} description={workspaceName ? t("au.selectDoc.withWorkspace", { name: workspaceName }) : t("au.selectDoc.noWorkspace")}>
      <Button asChild><Link to="/configure/workspaces">{t("au.openWorkspaces")}</Link></Button>
    </EmptyState></div>;
  return <div className="grid gap-6">
    {header}
    <section aria-label={t("au.activeContext")} className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-lg border bg-card px-4 py-3 text-sm">
      <span><span className="text-muted-foreground">{t("ctx.workspace")}</span> {workspaceName}</span>
      <span><span className="text-muted-foreground">{t("au.document")}</span> {documentId}{documentTitle ? ` (${documentTitle})` : ""}</span>
      <NextAction documentId={documentId} />
    </section>
    <Tabs value={tabs.some(id => id === tab) ? tab : "sources"} onValueChange={next => navigate(`/authoring/${next}`)}>
      <TabsList className="h-auto flex-wrap">{tabs.map(id => <TabsTrigger key={id} value={id}>{t(`au.tab.${id}`)}</TabsTrigger>)}</TabsList>
      <TabsContent value="sources"><SourcesPanel documentId={documentId} /></TabsContent>
      <TabsContent value="classification"><ClassificationPanel documentId={documentId} /></TabsContent>
      <TabsContent value="assets"><AssetsPanel documentId={documentId} /></TabsContent>
      <TabsContent value="context"><ContextPanel documentId={documentId} /></TabsContent>
      <TabsContent value="sections"><SectionsPanel documentId={documentId} /></TabsContent>
      <TabsContent value="revisions"><RevisionsPanel documentId={documentId} /></TabsContent>
    </Tabs>
  </div>;
}

export function AuthoringRoute() {
  const { t } = useT();
  const active = useActiveContext();
  const header = <PageHeader eyebrow={t("au.eyebrow")} title={t("au.title")} description={t("au.description")} />;
  return <QueryBoundary query={active} header={header}>{context => <AuthoringView header={header} context={context} />}</QueryBoundary>;
}
