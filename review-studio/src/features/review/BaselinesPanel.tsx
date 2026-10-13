import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import type { Baseline } from "@/api/domains/review";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { Facts, scalarRows } from "@/components/shared/Facts";
import { reviewKeys } from "./data";

function BaselineDetail({ workspaceId, id, onClose }: { workspaceId: string | null; id: string; onClose(): void }) {
  const api = useApi();
  const detail = useQuery({ queryKey: reviewKeys.baseline(workspaceId, id), queryFn: () => api.getBaseline!(id) });
  return <section aria-label="Baseline detail" className="grid gap-3 rounded-lg border bg-card p-4">
    <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Baseline {id}</h2><Button type="button" variant="outline" size="sm" onClick={onClose}>Close</Button></div>
    <QueryBoundary query={detail} title="Could not load the baseline" skeleton="h-16 w-full">{data => <Facts rows={scalarRows(data)} />}</QueryBoundary>
  </section>;
}

function BaselinesTable({ workspaceId, baselines }: { workspaceId: string | null; baselines: Baseline[] }) {
  const api = useApi();
  const [selected, setSelected] = useState<string | null>(null);
  if (baselines.length === 0) return <EmptyState title="No baselines yet" description="A baseline is the approved set of rendered pages a run is compared against. Promote one from a finished run's evidence.">
    <Button asChild><Link to="/review/evidence">Choose a run</Link></Button></EmptyState>;
  return <div className="grid gap-4">
    <Table aria-label="Baselines">
      <TableHeader><TableRow><TableHead>Baseline</TableHead><TableHead>Scope</TableHead><TableHead>Created</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
      <TableBody>{baselines.map(item => <TableRow key={item.id}>
        <TableCell className="font-medium">{item.name ?? item.id}</TableCell><TableCell>{item.scope ?? "-"}</TableCell>
        <TableCell>{item.created ?? String((item as Record<string, unknown>).created_at ?? "-")}</TableCell><TableCell><StatusBadge status={item.status ?? "unverified"} /></TableCell>
        <TableCell>{api.getBaseline && <Button type="button" variant="outline" size="sm" aria-label={`Details for ${item.id}`} onClick={() => setSelected(item.id)}>Details</Button>}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
    {selected && <BaselineDetail workspaceId={workspaceId} id={selected} onClose={() => setSelected(null)} />}
    <Button asChild variant="link" className="h-auto w-fit p-0"><Link to="/review/evidence">Promote another baseline from a run</Link></Button>
  </div>;
}

export function BaselinesPanel({ workspaceId }: { workspaceId: string | null }) {
  const api = useApi();
  const baselines = useQuery({ queryKey: reviewKeys.baselines(workspaceId), queryFn: () => api.listBaselines() });
  return <QueryBoundary query={baselines} title="Could not load baselines">{list => <BaselinesTable workspaceId={workspaceId} baselines={list} />}</QueryBoundary>;
}
