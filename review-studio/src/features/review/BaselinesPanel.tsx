import { formatApiError } from "@/api/errors";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { Facts, reviewKeys, scalarRows } from "./data";

function BaselineDetail({ workspaceId, id, onClose }: { workspaceId: string | null; id: string; onClose(): void }) {
  const api = useApi();
  const detail = useQuery({ queryKey: reviewKeys.baseline(workspaceId, id), queryFn: () => api.getBaseline!(id) });
  return <section aria-label="Baseline detail" className="grid gap-3 rounded-lg border bg-card p-4">
    <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Baseline {id}</h2><Button type="button" variant="outline" size="sm" onClick={onClose}>Close</Button></div>
    {detail.isPending ? <Skeleton className="h-16 w-full" /> : detail.isError ? <ErrorState title="Could not load the baseline" message={formatApiError(detail.error)} onRetry={() => void detail.refetch()} />
      : <Facts rows={scalarRows(detail.data)} />}
  </section>;
}

export function BaselinesPanel({ workspaceId }: { workspaceId: string | null }) {
  const api = useApi();
  const [selected, setSelected] = useState<string | null>(null);
  const baselines = useQuery({ queryKey: reviewKeys.baselines(workspaceId), queryFn: () => api.listBaselines() });
  if (baselines.isPending) return <Skeleton className="h-24 w-full" />;
  if (baselines.isError) return <ErrorState title="Could not load baselines" message={formatApiError(baselines.error)} onRetry={() => void baselines.refetch()} />;
  if (baselines.data.length === 0) return <EmptyState title="No baselines yet" description="A baseline is the approved set of rendered pages a run is compared against. Promote one from a finished run's evidence.">
    <Button asChild><Link to="/review/evidence">Choose a run</Link></Button></EmptyState>;
  return <div className="grid gap-4">
    <Table aria-label="Baselines">
      <TableHeader><TableRow><TableHead>Baseline</TableHead><TableHead>Scope</TableHead><TableHead>Created</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
      <TableBody>{baselines.data.map(item => {
        const raw = item as unknown as Record<string, unknown>;
        return <TableRow key={item.id}>
          <TableCell className="font-medium">{item.name ?? item.id}</TableCell><TableCell>{item.scope ?? "-"}</TableCell>
          <TableCell>{item.created ?? String(raw.created_at ?? "-")}</TableCell><TableCell><StatusBadge status={item.status ?? "unverified"} /></TableCell>
          <TableCell>{api.getBaseline && <Button type="button" variant="outline" size="sm" aria-label={`Details for ${item.id}`} onClick={() => setSelected(item.id)}>Details</Button>}</TableCell>
        </TableRow>;
      })}</TableBody>
    </Table>
    {selected && <BaselineDetail workspaceId={workspaceId} id={selected} onClose={() => setSelected(null)} />}
    <Button asChild variant="link" className="h-auto w-fit p-0"><Link to="/review/evidence">Promote another baseline from a run</Link></Button>
  </div>;
}
