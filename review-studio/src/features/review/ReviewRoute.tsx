import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useActiveContext, type ActiveContext } from "@/app/active-context";
import { EmptyState } from "@/components/shared/EmptyState";
import { PageHeader } from "@/components/shared/PageHeader";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Unavailable } from "@/components/shared/Unavailable";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCapability } from "@/lib/capability-registry";
import { useMode } from "@/app/mode";
import { useT, type MessageKey } from "@/lib/i18n";
import { ArtifactsPanel } from "./ArtifactsPanel";
import { BaselinesPanel } from "./BaselinesPanel";
import { DiffPanel } from "./DiffViewer";
import { EvidencePanel } from "./EvidencePanel";
import { FindingsPanel } from "./FindingsPanel";
import { GraphPanel } from "./GraphPanel";
import { QaPanel } from "./QaPanel";

/** [url segment, label key, Advanced only]. A hidden tab keeps its URL: it renders when linked to, it is just not listed. */
const tabs: ReadonlyArray<readonly [string, MessageKey, boolean]> = [
  ["findings", "review.tab.findings", false], ["artifacts", "review.tab.artifacts", false], ["evidence", "review.tab.evidence", true],
  ["baselines", "review.tab.baselines", true], ["diff", "review.tab.compare", false], ["qa", "review.tab.qa", true], ["graph", "review.tab.graph", true],
];

/** Tabs that render a read model the server catalogue lists under its own capability id. */
const gate: Record<string, string> = { findings: "findings.list", artifacts: "artifacts.list", baselines: "baselines.list", graph: "graph.read" };

function ReviewView({ header, context }: { header: ReactNode; context: ActiveContext }) {
  const { tab = "findings", id } = useParams();
  const navigate = useNavigate();
  const can = useCapability();
  const { advanced } = useMode();
  const { t } = useT();
  const { workspaceId } = context;
  if (!workspaceId) return <div className="grid gap-6">{header}
    <EmptyState title={t("rv.selectWorkspace.title")} description={t("rv.selectWorkspace.body")}><Button asChild><Link to="/configure/workspaces">{t("rv.openWorkspaces")}</Link></Button></EmptyState></div>;
  const current = tabs.some(([name]) => name === tab) ? tab : "findings";
  return <div className="grid gap-6">
    {header}
    <Tabs value={current} onValueChange={next => navigate(`/review/${next}`)}>
      <TabsList className="h-auto flex-wrap">{tabs.filter(([name, , advancedOnly]) => advanced || !advancedOnly || name === current).map(([name, label]) => <TabsTrigger key={name} value={name}>{t(label)}</TabsTrigger>)}</TabsList>
      {/* Every trigger names its panel through aria-controls, so the active panel must be a real tabpanel. */}
      <TabsContent value={current}>
        {gate[current] && !can(gate[current])
          ? <Unavailable>{t("rv.tabUnavailable", { tab: t(tabs.find(([name]) => name === current)![1]) })}</Unavailable>
          : <>
        {current === "findings" && <FindingsPanel workspaceId={workspaceId} selectedId={id} />}
        {current === "artifacts" && <ArtifactsPanel workspaceId={workspaceId} selectedId={id} />}
        {current === "evidence" && <EvidencePanel workspaceId={workspaceId} runId={id} />}
        {current === "baselines" && <BaselinesPanel workspaceId={workspaceId} />}
        {current === "diff" && <DiffPanel workspaceId={workspaceId} />}
        {current === "qa" && <QaPanel />}
        {current === "graph" && <GraphPanel workspaceId={workspaceId} />}
          </>}
      </TabsContent>
    </Tabs>
  </div>;
}

/** `/review/:tab/:id`: the id is a finding, an artifact, or a run depending on the tab. */
export function ReviewRoute() {
  const { t } = useT();
  const active = useActiveContext();
  const header = <PageHeader eyebrow={t("rv.eyebrow")} title={t("rv.title")} description={t("rv.description")} />;
  return <QueryBoundary query={active} header={header}>{context => <ReviewView header={header} context={context} />}</QueryBoundary>;
}
