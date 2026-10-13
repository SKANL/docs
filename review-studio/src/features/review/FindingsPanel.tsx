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
import { SeverityBadge, reviewKeys, toFindingRow, type FindingRow } from "./data";

/** Where a finding came from and where to go next: its run's evidence, and the section to fix. */
export function FindingDetail({ finding }: { finding: FindingRow }) {
  return <section aria-label="Finding detail" className="grid gap-3 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">{finding.id}</h2><SeverityBadge severity={finding.severity} />{finding.status && <Badge variant="outline">{finding.status}</Badge>}</div>
    <p>{finding.message}</p>
    <Facts rows={[["Code", finding.code], ["Location", finding.location === "-" ? undefined : finding.location], ["Run", finding.runId], ["Linked evidence", finding.evidence]]} />
    <div className="flex flex-wrap gap-4 text-sm">
      {finding.runId && <Link className="underline underline-offset-4" to={`/review/evidence/${encodeURIComponent(finding.runId)}`}>Open run evidence</Link>}
      {finding.runId && <Link className="underline underline-offset-4" to={`/pipeline/runs/${encodeURIComponent(finding.runId)}`}>Open run</Link>}
      {finding.section && <Link className="underline underline-offset-4" to={`/authoring/sections?section=${encodeURIComponent(finding.section)}`}>Open in authoring section</Link>}
    </div>
  </section>;
}

const severities = ["all", "critical", "high", "medium", "low"];

function FindingsTable({ all, selectedId }: { all: FindingRow[]; selectedId?: string }) {
  const [filter, setFilter] = useState("");
  const [severity, setSeverity] = useState("all");
  if (all.length === 0) return <EmptyState title="No findings" description="Findings appear here after a run is verified. A clean workspace has none." />;
  const needle = filter.trim().toLowerCase();
  const rows = all.filter(item => (severity === "all" || item.severity === severity) && (!needle || `${item.id} ${item.message} ${item.location} ${item.severity}`.toLowerCase().includes(needle)));
  const selected = selectedId ? all.find(item => item.id === selectedId) : undefined;
  return <div className="grid gap-4">
    <div className="flex flex-wrap items-end gap-4">
      <div className="grid gap-1"><Label htmlFor="finding-filter">Filter findings</Label><Input id="finding-filter" className="w-64" value={filter} onChange={event => setFilter(event.target.value)} /></div>
      <div className="grid gap-1"><Label htmlFor="finding-severity">Severity</Label>
        <Select value={severity} onValueChange={setSeverity}>
          <SelectTrigger id="finding-severity" aria-label="Severity" className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>{severities.map(value => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
        </Select></div>
    </div>
    <Table aria-label="Findings">
      <TableHeader><TableRow><TableHead>Finding</TableHead><TableHead>Severity</TableHead><TableHead>Message</TableHead><TableHead>Location</TableHead><TableHead>Run</TableHead></TableRow></TableHeader>
      <TableBody>{rows.map(item => <TableRow key={item.id}>
        <TableCell><Link className="font-medium underline-offset-4 hover:underline" to={`/review/findings/${encodeURIComponent(item.id)}`}>{item.id}</Link></TableCell>
        <TableCell><SeverityBadge severity={item.severity} /></TableCell>
        <TableCell className="whitespace-normal">{item.message}</TableCell>
        <TableCell>{item.location}</TableCell>
        <TableCell>{item.runId ?? "-"}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
    {rows.length === 0 && <p className="text-sm text-muted-foreground" role="status">No finding matches this filter.</p>}
    {selected ? <FindingDetail finding={selected} /> : selectedId && <p className="text-sm text-muted-foreground" role="status">Finding {selectedId} is not in this workspace.</p>}
  </div>;
}

export function FindingsPanel({ workspaceId, selectedId }: { workspaceId: string | null; selectedId?: string }) {
  const api = useApi();
  const findings = useQuery({ queryKey: reviewKeys.findings(workspaceId), queryFn: async () => (await api.listFindings()).map(toFindingRow) });
  return <QueryBoundary query={findings} title="Could not load findings">{all => <FindingsTable all={all} selectedId={selectedId} />}</QueryBoundary>;
}
