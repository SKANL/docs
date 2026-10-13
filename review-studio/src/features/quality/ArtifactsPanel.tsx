import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { StatusBadge } from "@/components/StatusBadge";
import type { Artifact } from "@/api/models";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorText, useCapability } from "@/features/authoring/data";
import { Digest, Facts, reviewKeys } from "./data";
import { ArtifactPreview, InspectionPanel } from "./inspection";

function ArtifactDetail({ workspaceId, artifact }: { workspaceId: string | null; artifact: Artifact }) {
  const api = useApi();
  const can = useCapability();
  const [inspecting, setInspecting] = useState(false);
  return <section aria-label="Artifact detail" className="grid gap-4 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center gap-3"><h2 className="text-lg font-semibold">{artifact.name}</h2><StatusBadge status={artifact.status} /></div>
    <Facts rows={[["Artifact id", artifact.id], ["Kind", artifact.kind], ["Size", artifact.size], ["Pages", artifact.pages?.toString()], ["Checksum", <Digest key="d" value={artifact.checksum} />]]} />
    <div className="flex flex-wrap items-center gap-4 text-sm">
      {artifact.runId && <Link className="underline underline-offset-4" to={`/review/evidence/${encodeURIComponent(artifact.runId)}`}>Open run evidence</Link>}
      {can("document.inspect") && api.inspectArtifact && <Button type="button" variant="outline" size="sm" aria-pressed={inspecting} onClick={() => setInspecting(value => !value)}>{inspecting ? "Hide inspection" : "Inspect artifact"}</Button>}
    </div>
    {inspecting && <InspectionPanel workspaceId={workspaceId} artifactId={artifact.id} />}
    <ArtifactPreview workspaceId={workspaceId} artifact={artifact} />
  </section>;
}

export function ArtifactsPanel({ workspaceId, selectedId }: { workspaceId: string | null; selectedId?: string }) {
  const api = useApi();
  const [runId, setRunId] = useState("all");
  const artifacts = useQuery({ queryKey: reviewKeys.artifacts(workspaceId), queryFn: () => api.listArtifacts() });
  const runs = useQuery({ queryKey: reviewKeys.runs(workspaceId), queryFn: async () => (await api.listRunPage!()).items });
  if (artifacts.isPending) return <Skeleton className="h-24 w-full" />;
  if (artifacts.isError) return <ErrorState title="Could not load artifacts" message={errorText(artifacts.error, "artifacts")} onRetry={() => void artifacts.refetch()} />;
  const all = artifacts.data;
  if (all.length === 0) return <EmptyState title="No artifacts" description="Artifacts appear here after a build produces output for a run." />;
  const rows = runId === "all" ? all : all.filter(item => item.runId === runId);
  const selected = selectedId ? all.find(item => item.id === selectedId) : undefined;
  return <div className="grid gap-4">
    <div className="grid w-fit gap-1"><Label htmlFor="artifact-run">Run</Label>
      <Select value={runId} onValueChange={setRunId}>
        <SelectTrigger id="artifact-run" aria-label="Run" className="w-56"><SelectValue /></SelectTrigger>
        <SelectContent><SelectItem value="all">All runs</SelectItem>{(runs.data ?? []).map(run => <SelectItem key={run.id} value={run.id}>{run.id}</SelectItem>)}</SelectContent>
      </Select></div>
    <Table aria-label="Artifacts">
      <TableHeader><TableRow><TableHead>Artifact</TableHead><TableHead>Kind</TableHead><TableHead>Size</TableHead><TableHead>Status</TableHead><TableHead>Run</TableHead></TableRow></TableHeader>
      <TableBody>{rows.map(item => <TableRow key={item.id}>
        <TableCell><Link className="font-medium underline-offset-4 hover:underline" to={`/review/artifacts/${encodeURIComponent(item.id)}`}>{item.name}</Link></TableCell>
        <TableCell>{item.kind}</TableCell><TableCell>{item.size}</TableCell><TableCell><StatusBadge status={item.status} /></TableCell><TableCell>{item.runId ?? "-"}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
    {selected ? <ArtifactDetail workspaceId={workspaceId} artifact={selected} /> : selectedId && <p className="text-sm text-muted-foreground" role="status">Artifact {selectedId} is not in this workspace.</p>}
  </div>;
}
