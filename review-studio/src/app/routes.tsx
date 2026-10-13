import { Link, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { areas, legacyScreens, type Area } from "@/app/areas";
import { AppShell } from "@/app/shell/AppShell";
import { useApi } from "@/app/providers";
import { LegacyRoute } from "@/app/legacy-pages";
import { EmptyState } from "@/components/shared/EmptyState";
import { PageHeader } from "@/components/shared/PageHeader";
import { Button } from "@/components/ui/button";
import { AuthoringRoute } from "@/features/authoring/AuthoringRoute";
import { WorkspaceDocumentPage } from "@/features/workspace/WorkspaceDocumentPage";

/** An area with no feature yet. Honest by construction: no actions, only where it will arrive. */
function AreaPlaceholder({ area }: { area: Area }) {
  return <div className="grid gap-6">
    <PageHeader eyebrow="Task area" title={area.label} description={area.summary} />
    <EmptyState title="Not available yet" description={`This area is delivered in ${area.slice}. Until then, use the legacy screens in the sidebar.`}>
      {area.id === "home" && <Button asChild variant="outline"><Link to="/legacy/overview">Open legacy overview</Link></Button>}
    </EmptyState>
  </div>;
}

function ConfigureIndex() {
  const area = areas.find(item => item.id === "configure")!;
  return <div className="grid gap-6">
    <PageHeader eyebrow="Task area" title={area.label} description={area.summary} />
    <Button asChild className="w-fit"><Link to="/configure/workspaces">Workspaces and documents</Link></Button>
    <EmptyState title="Not available yet" description={`Templates, plugins, rules, and diagnostics arrive in ${area.slice}.`} />
  </div>;
}

function Workspaces() { return <WorkspaceDocumentPage api={useApi()} />; }

function LegacyScreen() {
  const { id = "overview" } = useParams();
  const navigate = useNavigate();
  const api = useApi();
  // ponytail: legacy screens keep their light hard-coded palette inside a light surface until S7.2 retires them.
  return <div className="legacy rounded-xl bg-[#f6f8fb] p-6 text-[#17233c] [color-scheme:light]">
    <LegacyRoute route={id} api={api} go={next => navigate(next === "workspace" ? "/configure/workspaces" : `/legacy/${next}`)} />
  </div>;
}

export function AppRoutes({ pollIntervalMs }: { pollIntervalMs?: number }) {
  return <Routes>
    <Route element={<AppShell pollIntervalMs={pollIntervalMs} />}>
      <Route index element={<AreaPlaceholder area={areas[0]} />} />
      {areas.filter(area => !["home", "configure", "authoring"].includes(area.id)).map(area => <Route key={area.id} path={area.id} element={<AreaPlaceholder area={area} />} />)}
      <Route path="authoring/:tab?" element={<AuthoringRoute />} />
      <Route path="configure" element={<ConfigureIndex />} />
      <Route path="configure/workspaces" element={<Workspaces />} />
      <Route path="legacy/:id" element={<LegacyScreen />} />
      {/* Old hash URLs (#workspace, #runs, ...) keep working. */}
      <Route path="workspace" element={<Navigate to="/configure/workspaces" replace />} />
      {legacyScreens.map(([id]) => <Route key={id} path={id} element={<Navigate to={`/legacy/${id}`} replace />} />)}
      <Route path="*" element={<EmptyState title="Page not found" description="This address does not match any Review Studio page."><Button asChild variant="outline"><Link to="/">Go home</Link></Button></EmptyState>} />
    </Route>
  </Routes>;
}
