import { formatApiError } from "@/api/errors";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import type { GraphQuery, GraphQueryResult } from "@/api/models";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { reviewKeys, scalarRows } from "./data";

const queries: Array<{ query: GraphQuery; label: string; idLabel?: string }> = [
  { query: "claims_without_evidence", label: "Claims without evidence" },
  { query: "findings_affected_by_revision", label: "Findings affected by revision", idLabel: "Revision id" },
  { query: "artifacts_derived_from_input", label: "Artifacts derived from input", idLabel: "Input id" },
  { query: "unused_references", label: "Unused references" },
  { query: "unmet_requirements", label: "Unmet requirements" },
];

function QueryResults({ result }: { result: GraphQueryResult }) {
  if (result.graphUnavailable) return <Alert role="alert"><AlertTitle>The graph read model is unavailable</AlertTitle><AlertDescription>
    {result.warnings?.length ? result.warnings.map(warning => <p key={warning}>{warning}</p>) : <p>No reason was reported.</p>}</AlertDescription></Alert>;
  if (result.items.length === 0) return <p className="text-sm text-muted-foreground" role="status">No items match this query.</p>;
  return <Table aria-label="Query results">
    <TableHeader><TableRow><TableHead>Id</TableHead><TableHead>Kind</TableHead><TableHead>Label</TableHead><TableHead>Confidence</TableHead><TableHead>Attributes</TableHead></TableRow></TableHeader>
    <TableBody>{result.items.map(item => <TableRow key={item.id}>
      <TableCell className="font-medium">{item.id}</TableCell><TableCell>{item.kind}</TableCell><TableCell className="whitespace-normal">{item.label}</TableCell>
      <TableCell>{item.confidence === undefined ? "-" : `${Math.round(item.confidence * 100)}%`}</TableCell>
      <TableCell className="whitespace-normal">{scalarRows(item.attributes ?? {}).map(([key, value]) => `${key}: ${value}`).join("; ") || "-"}</TableCell>
    </TableRow>)}</TableBody>
  </Table>;
}

export function GraphPanel({ workspaceId }: { workspaceId: string | null }) {
  const api = useApi();
  const [selected, setSelected] = useState<GraphQuery>("claims_without_evidence");
  const [id, setId] = useState("");
  const [missing, setMissing] = useState("");
  const graph = useQuery({ queryKey: reviewKeys.graph(workspaceId), queryFn: () => api.getGraph() });
  const run = useMutation({ mutationFn: () => api.getGraphQuery(selected, id.trim() || undefined) });
  const option = queries.find(item => item.query === selected)!;
  const start = () => {
    if (option.idLabel && !id.trim()) { setMissing(`${option.idLabel} is required for this query.`); return; }
    setMissing(""); run.mutate();
  };
  return <div className="grid gap-6">
    <section aria-label="Graph overview" className="grid gap-2">
      <h2 className="text-xl font-semibold">Graph</h2>
      {graph.isPending ? <Skeleton className="h-16 w-full" /> : graph.isError ? <ErrorState title="Could not load the graph" message={formatApiError(graph.error)} onRetry={() => void graph.refetch()} />
        : graph.data.nodes.length === 0 ? <EmptyState title="The semantic graph is empty" description="Claims, sources, and artifacts are linked here once a run has produced evidence. Run the pipeline, then come back." />
        : <p className="text-sm">{graph.data.nodes.length} nodes and {graph.data.edges.length} links connect claims, sources, sections, and artifacts.</p>}
    </section>
    <section aria-label="Graph queries" className="grid gap-3 rounded-lg border bg-card p-4">
      <h3 className="text-lg font-semibold">Read-only queries</h3>
      <p className="text-sm text-muted-foreground">Results are exploratory views, not attestations. Read them with the run&apos;s evidence before treating an item as proof.</p>
      <div className="flex flex-wrap items-end gap-4">
        <div className="grid gap-1"><Label htmlFor="graph-query">Query</Label>
          <Select value={selected} onValueChange={value => { setSelected(value as GraphQuery); setMissing(""); run.reset(); }}>
            <SelectTrigger id="graph-query" aria-label="Query" className="w-72"><SelectValue /></SelectTrigger>
            <SelectContent>{queries.map(item => <SelectItem key={item.query} value={item.query}>{item.label}</SelectItem>)}</SelectContent>
          </Select></div>
        {option.idLabel && <div className="grid gap-1"><Label htmlFor="graph-query-id">{option.idLabel}</Label><Input id="graph-query-id" className="w-56" value={id} onChange={event => setId(event.target.value)} /></div>}
        <Button type="button" disabled={run.isPending} onClick={start}>Run query</Button>
      </div>
      {missing && <p className="text-sm text-destructive" role="alert">{missing}</p>}
      {run.isError && <ErrorState title="Could not run the query" message={formatApiError(run.error)} onRetry={start} retrying={run.isPending} />}
      {run.data && <QueryResults result={run.data} />}
    </section>
  </div>;
}
