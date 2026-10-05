import { lazy } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { areas } from "@/app/areas";
import { AppShell } from "@/app/shell/AppShell";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { Button } from "@/components/ui/button";
import { ConfigureLayout, configureSections } from "@/features/templates/ConfigureLayout";

// Each feature area is its own chunk so the entry bundle holds only the shell (budget: docs/review-studio/release-proof.md).
const HomePage = lazy(() => import("@/features/home/HomePage").then(m => ({ default: m.HomePage })));
const AuthoringRoute = lazy(() => import("@/features/authoring/AuthoringRoute").then(m => ({ default: m.AuthoringRoute })));
const PipelineRoute = lazy(() => import("@/features/pipeline/PipelineRoute").then(m => ({ default: m.PipelineRoute })));
const RunDetailPage = lazy(() => import("@/features/pipeline/RunDetailPage").then(m => ({ default: m.RunDetailPage })));
const QualityRoute = lazy(() => import("@/features/quality/QualityRoute").then(m => ({ default: m.QualityRoute })));
const DeliveryRoute = lazy(() => import("@/features/delivery/DeliveryRoute").then(m => ({ default: m.DeliveryRoute })));
const ToolsRoute = lazy(() => import("@/features/tools/ToolsRoute").then(m => ({ default: m.ToolsRoute })));
const WorkspaceDocumentPage = lazy(() => import("@/features/workspace/WorkspaceDocumentPage").then(m => ({ default: m.WorkspaceDocumentPage })));
const TemplateEditorPage = lazy(() => import("@/features/templates/TemplateEditorPage").then(m => ({ default: m.TemplateEditorPage })));
const DoctorPanel = lazy(() => import("@/features/templates/DoctorPanel").then(m => ({ default: m.DoctorPanel })));
const PluginsPanel = lazy(() => import("@/features/templates/PluginsPanel").then(m => ({ default: m.PluginsPanel })));

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
