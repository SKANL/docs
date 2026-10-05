import { Link, useNavigate, useParams } from "react-router-dom";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { PageHeader } from "@/components/shared/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorText, useActiveContext } from "@/features/authoring/data";
import { ArtifactsPanel } from "./ArtifactsPanel";
import { BaselinesPanel } from "./BaselinesPanel";
import { DiffPanel } from "./DiffViewer";
import { EvidencePanel } from "./EvidencePanel";
import { FindingsPanel } from "./FindingsPanel";
import { GraphPanel } from "./GraphPanel";
import { QaPanel } from "./QaPanel";

const tabs = [["findings", "Findings"], ["artifacts", "Artifacts"], ["evidence", "Evidence"], ["baselines", "Baselines"], ["diff", "Diff"], ["qa", "Quality checks"], ["graph", "Graph"]] as const;

/** `/review/:tab/:id`: the id is a finding, an artifact, or a run depending on the tab. */
export function QualityRoute() {
  const { tab = "findings", id } = useParams();
  const navigate = useNavigate();
  const active = useActiveContext();
  const header = <PageHeader eyebrow="Task area" title="Review" description="Follow a failing run to its finding, previews, input evidence, and the next operation." />;
  if (active.isPending) return <div className="grid gap-6">{header}<Skeleton className="h-24 w-full" /></div>;
  if (active.isError) return <div className="grid gap-6">{header}<ErrorState message={errorText(active.error, "workspace")} onRetry={() => void active.refetch()} /></div>;
  const { workspaceId } = active.data;
  if (!workspaceId) return <div className="grid gap-6">{header}
    <EmptyState title="Select a workspace first" description="Findings, artifacts, and evidence belong to a workspace."><Button asChild><Link to="/configure/workspaces">Open workspaces and documents</Link></Button></EmptyState></div>;
  const current = tabs.some(([name]) => name === tab) ? tab : "findings";
  return <div className="grid gap-6">
    {header}
    <Tabs value={current} onValueChange={next => navigate(`/review/${next}`)}>
      <TabsList className="h-auto flex-wrap">{tabs.map(([name, label]) => <TabsTrigger key={name} value={name}>{label}</TabsTrigger>)}</TabsList>
      {/* Every trigger names its panel through aria-controls, so the active panel must be a real tabpanel. */}
      <TabsContent value={current}>
        {current === "findings" && <FindingsPanel workspaceId={workspaceId} selectedId={id} />}
        {current === "artifacts" && <ArtifactsPanel workspaceId={workspaceId} selectedId={id} />}
        {current === "evidence" && <EvidencePanel workspaceId={workspaceId} runId={id} />}
        {current === "baselines" && <BaselinesPanel workspaceId={workspaceId} />}
        {current === "diff" && <DiffPanel workspaceId={workspaceId} />}
        {current === "qa" && <QaPanel />}
        {current === "graph" && <GraphPanel workspaceId={workspaceId} />}
      </TabsContent>
    </Tabs>
  </div>;
}
