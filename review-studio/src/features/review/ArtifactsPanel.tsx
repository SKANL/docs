import { useT } from "@/lib/i18n";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { useMode } from "@/app/mode";
import { EmptyState } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { StatusBadge } from "@/components/shared/StatusBadge";
import type { Artifact } from "@/api/models";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCapability } from "@/lib/capability-registry";
import { Digest, Facts } from "@/components/shared/Facts";
import { reviewKeys } from "./data";
import { ArtifactPreview, InspectionPanel } from "./inspection";

function ArtifactDetail({ workspaceId, artifact }: { workspaceId: string | null; artifact: Artifact }) {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const { advanced } = useMode();
  const [inspecting, setInspecting] = useState(false);
  return <section aria-label={t("rv.art.detail")} className="grid gap-4 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center gap-3"><h2 className="text-lg font-semibold">{artifact.name}</h2><StatusBadge status={artifact.status} /></div>
    <Facts rows={[[t("rv.art.id"), artifact.id], [t("rv.art.kind"), artifact.kind], [t("rv.art.size"), artifact.size], [t("rv.art.pages"), artifact.pages?.toString()], [t("rv.art.checksum"), advanced ? <Digest key="d" value={artifact.checksum} /> : undefined]]} />
    <div className="flex flex-wrap items-center gap-4 text-sm">
      {artifact.runId && <Link className="underline underline-offset-4" to={`/review/evidence/${encodeURIComponent(artifact.runId)}`}>{t("rv.finding.openEvidence")}</Link>}
      {can("document.inspect") && api.inspectArtifact && <Button type="button" variant="outline" size="sm" aria-pressed={inspecting} onClick={() => setInspecting(value => !value)}>{inspecting ? t("rv.art.hideInspection") : t("rv.art.inspect")}</Button>}
    </div>
    {inspecting && <InspectionPanel workspaceId={workspaceId} artifactId={artifact.id} />}
    <ArtifactPreview workspaceId={workspaceId} artifact={artifact} />
  </section>;
}

function ArtifactsTable({ workspaceId, all, selectedId }: { workspaceId: string | null; all: Artifact[]; selectedId?: string }) {
  const api = useApi();
  const { t } = useT();
  const [runId, setRunId] = useState("all");
  const runs = useQuery({ queryKey: reviewKeys.runs(workspaceId), queryFn: async () => (await api.listRunPage!()).items });
  if (all.length === 0) return <EmptyState title={t("rv.art.none.title")} description={t("rv.art.none.body")} action={{ label: t("empty.runPipeline"), to: "/pipeline" }} />;
  const rows = runId === "all" ? all : all.filter(item => item.runId === runId);
  const selected = selectedId ? all.find(item => item.id === selectedId) : undefined;
  return <div className="grid gap-4">
    <div className="grid w-fit gap-1"><Label htmlFor="artifact-run">{t("rv.art.run")}</Label>
      <Select value={runId} onValueChange={setRunId}>
        <SelectTrigger id="artifact-run" aria-label={t("rv.art.run")} className="w-56"><SelectValue /></SelectTrigger>
        <SelectContent><SelectItem value="all">{t("rv.art.allRuns")}</SelectItem>{(runs.data ?? []).map(run => <SelectItem key={run.id} value={run.id}>{run.id}</SelectItem>)}</SelectContent>
      </Select></div>
    <Table aria-label={t("rv.art.table")}>
      <TableHeader><TableRow><TableHead>{t("rv.art.col")}</TableHead><TableHead>{t("rv.art.kind")}</TableHead><TableHead>{t("rv.art.size")}</TableHead><TableHead>{t("rv.art.status")}</TableHead><TableHead>{t("rv.art.run")}</TableHead></TableRow></TableHeader>
      <TableBody>{rows.map(item => <TableRow key={item.id}>
        <TableCell><Link className="font-medium underline-offset-4 hover:underline" to={`/review/artifacts/${encodeURIComponent(item.id)}`}>{item.name}</Link></TableCell>
        <TableCell>{item.kind}</TableCell><TableCell>{item.size}</TableCell><TableCell><StatusBadge status={item.status} /></TableCell><TableCell>{item.runId ?? "-"}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
    {selected ? <ArtifactDetail workspaceId={workspaceId} artifact={selected} /> : selectedId && <p className="text-sm text-muted-foreground" role="status">{t("rv.art.notHere", { id: selectedId })}</p>}
  </div>;
}

export function ArtifactsPanel({ workspaceId, selectedId }: { workspaceId: string | null; selectedId?: string }) {
  const { t } = useT();
  const api = useApi();
  const artifacts = useQuery({ queryKey: reviewKeys.artifacts(workspaceId), queryFn: () => api.listArtifacts() });
  return <QueryBoundary query={artifacts} title={t("rv.art.loadFailed")}>{all => <ArtifactsTable workspaceId={workspaceId} all={all} selectedId={selectedId} />}</QueryBoundary>;
}
