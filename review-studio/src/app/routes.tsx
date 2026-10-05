import { Link, Navigate, Route, Routes } from "react-router-dom";
import { areas } from "@/app/areas";
import { AppShell } from "@/app/shell/AppShell";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { Button } from "@/components/ui/button";
import { ConfigureLayout, configureSections } from "@/features/templates/ConfigureLayout";
import { DoctorPanel } from "@/features/templates/DoctorPanel";
import { PluginsPanel } from "@/features/templates/PluginsPanel";
import { TemplateEditorPage } from "@/features/templates/TemplateEditorPage";
import { ToolsRoute } from "@/features/tools/ToolsRoute";
import { DeliveryRoute } from "@/features/delivery/DeliveryRoute";
import { AuthoringRoute } from "@/features/authoring/AuthoringRoute";
import { QualityRoute } from "@/features/quality/QualityRoute";
import { PipelineRoute } from "@/features/pipeline/PipelineRoute";
import { RunDetailPage } from "@/features/pipeline/RunDetailPage";
import { HomePage } from "@/features/home/HomePage";
import { WorkspaceDocumentPage } from "@/features/workspace/WorkspaceDocumentPage";

function ConfigureIndex() {
  const area = areas.find(item => item.id === "configure")!;
  return <ConfigureLayout title={area.label} description={area.summary}>
    <ul aria-label="Configure areas" className="grid gap-3 sm:grid-cols-2">
      {configureSections.map(([id, label, text]) => <li key={id} className="rounded-lg border bg-card p-4"><Button asChild variant="link" className="h-auto p-0 text-base"><Link to={`/configure/${id}`}>{label}</Link></Button><p className="mt-1 text-sm text-muted-foreground">{text}</p></li>)}
    </ul>
  </ConfigureLayout>;
}

const legacyHashes: Record<string, string> = {
  overview: "/", workspace: "/configure/workspaces", runs: "/pipeline", findings: "/review/findings", artifacts: "/review/artifacts", passport: "/review/evidence",
  graph: "/review/graph", baselines: "/review/baselines", revisions: "/authoring/revisions", templates: "/configure/templates", plugins: "/configure/plugins", publication: "/delivery",
};

function Workspaces() { return <WorkspaceDocumentPage api={useApi()} />; }

export function AppRoutes({ pollIntervalMs }: { pollIntervalMs?: number }) {
  return <Routes>
    <Route element={<AppShell pollIntervalMs={pollIntervalMs} />}>
      <Route index element={<HomePage />} />
      <Route path="authoring/:tab?" element={<AuthoringRoute />} />
      <Route path="pipeline" element={<PipelineRoute />} />
      <Route path="pipeline/runs/:runId" element={<RunDetailPage />} />
      <Route path="review/:tab?/:id?" element={<QualityRoute />} />
      <Route path="delivery" element={<DeliveryRoute />} />
      <Route path="configure" element={<ConfigureIndex />} />
      <Route path="configure/workspaces" element={<Workspaces />} />
      <Route path="configure/templates" element={<ConfigureLayout title="Templates" description="Installed and built-in templates, creation, and validation."><TemplateEditorPage /></ConfigureLayout>} />
      <Route path="configure/diagnostics" element={<ConfigureLayout title="Diagnostics" description="Environment checks for the current document and issue-code explanations."><DoctorPanel /></ConfigureLayout>} />
      <Route path="configure/plugins" element={<ConfigureLayout title="Plugins" description="The read-only plugin registry."><PluginsPanel /></ConfigureLayout>} />
      <Route path="tools" element={<ToolsRoute />} />
      {/* Old hash URLs (#runs, #findings, ...) keep working. */}
      {Object.entries(legacyHashes).map(([from, to]) => <Route key={from} path={from} element={<Navigate to={to} replace />} />)}
      <Route path="*" element={<EmptyState title="Page not found" description="This address does not match any Review Studio page."><Button asChild variant="outline"><Link to="/">Go home</Link></Button></EmptyState>} />
    </Route>
  </Routes>;
}
