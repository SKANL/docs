import { useT } from "@/lib/i18n";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { Facts } from "@/components/shared/Facts";
import { SeverityBadge, findingLocation, reviewKeys, toFindingRow, type FindingRow } from "./data";
import { statusKey } from "@/lib/i18n";

/** Where a finding came from and where to go next: its run's evidence, and the section to fix. */
function FindingDetail({ finding }: { finding: FindingRow }) {
  const { t } = useT();
  const location = findingLocation(finding, t);
  const statusText = finding.status && statusKey("status", finding.status);
  return <section aria-label={t("rv.finding.detail")} className="grid gap-3 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">{finding.id}</h2><SeverityBadge severity={finding.severity} />{finding.status && <Badge variant="outline">{statusText ? t(statusText) : finding.status}</Badge>}</div>
    <p>{finding.message || t("rv.noDescription")}</p>
    <Facts rows={[[t("rv.finding.code"), finding.code], [t("rv.finding.location"), location === "-" ? undefined : location], [t("rv.finding.run"), finding.runId], [t("rv.finding.evidence"), finding.evidence]]} />
    <div className="flex flex-wrap gap-4 text-sm">
      {finding.runId && <Link className="underline underline-offset-4" to={`/review/evidence/${encodeURIComponent(finding.runId)}`}>{t("rv.finding.openEvidence")}</Link>}
      {finding.runId && <Link className="underline underline-offset-4" to={`/pipeline/runs/${encodeURIComponent(finding.runId)}`}>{t("rv.finding.openRun")}</Link>}
      {finding.section && <Link className="underline underline-offset-4" to={`/authoring/sections?section=${encodeURIComponent(finding.section)}`}>{t("rv.finding.openSection")}</Link>}
    </div>
  </section>;
}

const severities = ["all", "critical", "high", "medium", "low"];

function FindingsTable({ all, selectedId }: { all: FindingRow[]; selectedId?: string }) {
  const { t } = useT();
  const [filter, setFilter] = useState("");
  const [severity, setSeverity] = useState("all");
  if (all.length === 0) return <EmptyState title={t("rv.finding.none.title")} description={t("rv.finding.none.body")} action={{ label: t("empty.runPipeline"), to: "/pipeline" }} />;
  const needle = filter.trim().toLowerCase();
  const severityLabel = (value: string) => { const key = statusKey("rv.sev", value); return key ? t(key) : value; }; // what the table shows
  const rows = all.filter(item => (severity === "all" || item.severity === severity) && (!needle || `${item.id} ${item.message} ${findingLocation(item, t)} ${item.severity} ${severityLabel(item.severity)}`.toLowerCase().includes(needle)));
  const selected = selectedId ? all.find(item => item.id === selectedId) : undefined;
  return <div className="grid gap-4">
    <div className="flex flex-wrap items-end gap-4">
      <div className="grid gap-1"><Label htmlFor="finding-filter">{t("rv.finding.filter")}</Label><Input id="finding-filter" className="w-64" value={filter} onChange={event => setFilter(event.target.value)} /></div>
      <div className="grid gap-1"><Label htmlFor="finding-severity">{t("rv.finding.severity")}</Label>
        <Select value={severity} onValueChange={setSeverity}>
          <SelectTrigger id="finding-severity" aria-label={t("rv.finding.severity")} className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>{severities.map(value => <SelectItem key={value} value={value}>{t(statusKey("rv.sev", value) ?? "rv.sev.unknown")}</SelectItem>)}</SelectContent>
        </Select></div>
    </div>
    <Table aria-label={t("rv.finding.table")}>
      <TableHeader><TableRow><TableHead>{t("rv.finding.col")}</TableHead><TableHead>{t("rv.finding.severity")}</TableHead><TableHead>{t("rv.finding.message")}</TableHead><TableHead>{t("rv.finding.location")}</TableHead><TableHead>{t("rv.finding.run")}</TableHead></TableRow></TableHeader>
      <TableBody>{rows.map(item => <TableRow key={item.id}>
        <TableCell><Link className="font-medium underline-offset-4 hover:underline" to={`/review/findings/${encodeURIComponent(item.id)}`}>{item.id}</Link></TableCell>
        <TableCell><SeverityBadge severity={item.severity} /></TableCell>
        <TableCell className="whitespace-normal">{item.message || t("rv.noDescription")}</TableCell>
        <TableCell>{findingLocation(item, t)}</TableCell>
        <TableCell>{item.runId ?? "-"}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
    {rows.length === 0 && <p className="text-sm text-muted-foreground" role="status">{t("rv.finding.noMatch")}</p>}
    {selected ? <FindingDetail finding={selected} /> : selectedId && <p className="text-sm text-muted-foreground" role="status">{t("rv.finding.notHere", { id: selectedId })}</p>}
  </div>;
}

export function FindingsPanel({ workspaceId, selectedId }: { workspaceId: string | null; selectedId?: string }) {
  const { t } = useT();
  const api = useApi();
  const findings = useQuery({ queryKey: reviewKeys.findings(workspaceId), queryFn: async () => (await api.listFindings()).map(toFindingRow) });
  return <QueryBoundary query={findings} title={t("rv.finding.loadFailed")}>{all => <FindingsTable all={all} selectedId={selectedId} />}</QueryBoundary>;
}
