import { lazy } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { AppShell } from "@/app/shell/AppShell";
import { EmptyState } from "@/components/shared/EmptyState";
import { Button } from "@/components/ui/button";
import { ConfigureLayout } from "@/features/configure/ConfigureLayout";
import { useT } from "@/lib/i18n";

// Each feature area is its own chunk so the entry bundle holds only the shell (budget: docs/review-studio/release-proof.md).
const HomePage = lazy(() => import("@/features/home/HomePage").then(m => ({ default: m.HomePage })));
const AuthoringRoute = lazy(() => import("@/features/authoring/AuthoringRoute").then(m => ({ default: m.AuthoringRoute })));
const PipelineRoute = lazy(() => import("@/features/pipeline/PipelineRoute").then(m => ({ default: m.PipelineRoute })));
const RunDetailPage = lazy(() => import("@/features/pipeline/RunDetailPage").then(m => ({ default: m.RunDetailPage })));
const ReviewRoute = lazy(() => import("@/features/review/ReviewRoute").then(m => ({ default: m.ReviewRoute })));
const DeliveryRoute = lazy(() => import("@/features/delivery/DeliveryRoute").then(m => ({ default: m.DeliveryRoute })));
const ToolsRoute = lazy(() => import("@/features/tools/ToolsRoute").then(m => ({ default: m.ToolsRoute })));
const ConfigureIndex = lazy(() => import("@/features/configure/ConfigureIndex").then(m => ({ default: m.ConfigureIndex })));
const WorkspaceDocumentPage = lazy(() => import("@/features/workspace/WorkspaceDocumentPage").then(m => ({ default: m.WorkspaceDocumentPage })));
const TemplateEditorPage = lazy(() => import("@/features/templates/TemplateEditorPage").then(m => ({ default: m.TemplateEditorPage })));
const DoctorPanel = lazy(() => import("@/features/configure/DoctorPanel").then(m => ({ default: m.DoctorPanel })));
const PluginsPanel = lazy(() => import("@/features/configure/PluginsPanel").then(m => ({ default: m.PluginsPanel })));

export function AppRoutes({ pollIntervalMs }: { pollIntervalMs?: number }) {
  const { t } = useT();
  return <Routes>
    <Route element={<AppShell pollIntervalMs={pollIntervalMs} />}>
      <Route index element={<HomePage />} />
      <Route path="authoring/:tab?" element={<AuthoringRoute />} />
      <Route path="pipeline" element={<PipelineRoute />} />
      <Route path="pipeline/runs/:runId" element={<RunDetailPage />} />
      <Route path="review/:tab?/:id?" element={<ReviewRoute />} />
      <Route path="delivery" element={<DeliveryRoute />} />
      <Route path="configure" element={<ConfigureIndex />} />
      <Route path="configure/workspaces" element={<WorkspaceDocumentPage />} />
      <Route path="configure/templates" element={<ConfigureLayout title="cfg.templates" description="cfg.templates.text"><TemplateEditorPage /></ConfigureLayout>} />
      <Route path="configure/diagnostics" element={<ConfigureLayout title="cfg.diagnostics" description="cfg.diagnostics.page"><DoctorPanel /></ConfigureLayout>} />
      <Route path="configure/plugins" element={<ConfigureLayout title="cfg.plugins" description="cfg.plugins.text"><PluginsPanel /></ConfigureLayout>} />
      <Route path="tools" element={<ToolsRoute />} />
      <Route path="*" element={<EmptyState title={t("app.notFound.title")} description={t("app.notFound.body")}><Button asChild variant="outline"><Link to="/">{t("app.goHome")}</Link></Button></EmptyState>} />
    </Route>
  </Routes>;
}
