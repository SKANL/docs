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
import { useT } from "@/lib/i18n";
import { reviewKeys } from "./data";

function BaselineDetail({ workspaceId, id, onClose }: { workspaceId: string | null; id: string; onClose(): void }) {
  const { t } = useT();
  const api = useApi();
  const detail = useQuery({ queryKey: reviewKeys.baseline(workspaceId, id), queryFn: () => api.getBaseline!(id) });
  return <section aria-label={t("rv.bl.detail")} className="grid gap-3 rounded-lg border bg-card p-4">
    <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">{t("rv.bl.title", { id })}</h2><Button type="button" variant="outline" size="sm" onClick={onClose}>{t("common.close")}</Button></div>
    <QueryBoundary query={detail} title={t("rv.bl.loadFailed")} skeleton="h-16 w-full">{data => <Facts rows={scalarRows(data)} />}</QueryBoundary>
  </section>;
}

function BaselinesTable({ workspaceId, baselines }: { workspaceId: string | null; baselines: Baseline[] }) {
  const { t } = useT();
  const api = useApi();
  const [selected, setSelected] = useState<string | null>(null);
  if (baselines.length === 0) return <EmptyState title={t("rv.bl.none.title")} description={t("rv.bl.none.body")}>
    <Button asChild><Link to="/review/evidence">{t("rv.bl.chooseRun")}</Link></Button></EmptyState>;
  return <div className="grid gap-4">
    <Table aria-label={t("rv.bl.table")}>
      <TableHeader><TableRow><TableHead>{t("rv.bl.col")}</TableHead><TableHead>{t("rv.bl.scope")}</TableHead><TableHead>{t("rv.bl.created")}</TableHead><TableHead>{t("rv.bl.status")}</TableHead><TableHead /></TableRow></TableHeader>
      <TableBody>{baselines.map(item => <TableRow key={item.id}>
        <TableCell className="font-medium">{item.name ?? item.id}</TableCell><TableCell>{item.scope ?? "-"}</TableCell>
        <TableCell>{item.created ?? String((item as Record<string, unknown>).created_at ?? "-")}</TableCell><TableCell><StatusBadge status={item.status ?? "unverified"} /></TableCell>
        <TableCell>{api.getBaseline && <Button type="button" variant="outline" size="sm" aria-label={t("rv.bl.detailsLabel", { id: item.id })} onClick={() => setSelected(item.id)}>{t("rv.bl.details")}</Button>}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
    {selected && <BaselineDetail workspaceId={workspaceId} id={selected} onClose={() => setSelected(null)} />}
    <Button asChild variant="link" className="h-auto w-fit p-0"><Link to="/review/evidence">{t("rv.bl.promoteAnother")}</Link></Button>
  </div>;
}

export function BaselinesPanel({ workspaceId }: { workspaceId: string | null }) {
  const { t } = useT();
  const api = useApi();
  const baselines = useQuery({ queryKey: reviewKeys.baselines(workspaceId), queryFn: () => api.listBaselines() });
  return <QueryBoundary query={baselines} title={t("rv.bl.listFailed")}>{list => <BaselinesTable workspaceId={workspaceId} baselines={list} />}</QueryBoundary>;
}
