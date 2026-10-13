import { Link, useNavigate, useParams } from "react-router-dom";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { PageHeader } from "@/components/shared/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AssetsPanel } from "./AssetsPanel";
import { ClassificationPanel } from "./ClassificationPanel";
import { ContextPanel } from "./ContextPanel";
import { RevisionsPanel } from "./RevisionsPanel";
import { SectionsPanel } from "./SectionsPanel";
import { SourcesPanel } from "./SourcesPanel";
import { errorText, useActiveContext, useClassification, useContextStatus, useSections } from "./data";

const tabs = [["sources", "Sources"], ["classification", "Classification"], ["assets", "Assets"], ["context", "Context"], ["sections", "Sections"], ["revisions", "Revisions"]] as const;

/** One hint, derived only from which server data exists. It states no validity rule. */
function NextAction({ documentId }: { documentId: string }) {
  const sections = useSections(documentId);
  const classification = useClassification(documentId);
  const context = useContextStatus(documentId);
  const pending = classification.data?.filter(item => !item.confirmed_role).length ?? 0;
  const missing = context.data?.topics.filter(topic => topic.missing).map(topic => topic.title) ?? [];
  const hint: [string, string] | null = sections.data === undefined ? null
    : sections.data.length === 0 && !classification.data?.length ? ["Add sources", "sources"]
    : pending > 0 ? [`Confirm the role of ${pending} source${pending === 1 ? "" : "s"}`, "classification"]
    : missing.length > 0 ? [`Fill the missing context: ${missing.join(", ")}`, "context"]
    : sections.data.length > 0 ? ["Review your sections", "sections"] : null;
  if (!hint) return null;
  return <p role="status" className="text-sm">Next: <Button asChild variant="link" className="h-auto p-0"><Link to={`/authoring/${hint[1]}`}>{hint[0]}</Link></Button></p>;
}

export function AuthoringRoute() {
  const { tab = "sources" } = useParams();
  const navigate = useNavigate();
  const active = useActiveContext();
  const header = <PageHeader eyebrow="Task area" title="Authoring" description="Sources, classification, assets, context, sections, and revisions for the current document." />;
  if (active.isPending) return <div className="grid gap-6">{header}<Skeleton className="h-24 w-full" /></div>;
  if (active.isError) return <div className="grid gap-6">{header}<ErrorState message={errorText(active.error, "workspace")} onRetry={() => void active.refetch()} /></div>;
  const { workspaceName, documentId, documentTitle } = active.data;
  if (!documentId) return <div className="grid gap-6">{header}
    <EmptyState title="Select a document first" description={workspaceName ? `Workspace ${workspaceName} has no current document. Choose or create one to start authoring.` : "No workspace is selected yet. Create a workspace and a document to start authoring."}>
      <Button asChild><Link to="/configure/workspaces">Open workspaces and documents</Link></Button>
    </EmptyState></div>;
  return <div className="grid gap-6">
    {header}
    <section aria-label="Active context" className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-lg border bg-card px-4 py-3 text-sm">
      <span><span className="text-muted-foreground">Workspace</span> {workspaceName}</span>
      <span><span className="text-muted-foreground">Document</span> {documentId}{documentTitle ? ` (${documentTitle})` : ""}</span>
      <NextAction documentId={documentId} />
    </section>
    <Tabs value={tabs.some(([id]) => id === tab) ? tab : "sources"} onValueChange={next => navigate(`/authoring/${next}`)}>
      <TabsList className="h-auto flex-wrap">{tabs.map(([id, label]) => <TabsTrigger key={id} value={id}>{label}</TabsTrigger>)}</TabsList>
      <TabsContent value="sources"><SourcesPanel documentId={documentId} /></TabsContent>
      <TabsContent value="classification"><ClassificationPanel documentId={documentId} /></TabsContent>
      <TabsContent value="assets"><AssetsPanel documentId={documentId} /></TabsContent>
      <TabsContent value="context"><ContextPanel documentId={documentId} /></TabsContent>
      <TabsContent value="sections"><SectionsPanel documentId={documentId} /></TabsContent>
      <TabsContent value="revisions"><RevisionsPanel documentId={documentId} /></TabsContent>
    </Tabs>
  </div>;
}
