import { useT } from "@/lib/i18n";
import { formatApiError } from "@/api/errors";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import type { GraphQuery, GraphQueryResult } from "@/api/models";
import type { SectionCoverage } from "@/api/domains/review";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { scalarRows } from "@/components/shared/Facts";
import { reviewKeys } from "./data";

// `suggest`: node kinds whose ids the query takes, offered as completions for the id field.
const queries: Array<{ query: GraphQuery; label: string; idLabel?: string; suggest?: string[] }> = [
  { query: "claims_without_evidence", label: "Claims without evidence" },
  { query: "findings_affected_by_revision", label: "Findings affected by revision", idLabel: "Revision id", suggest: ["revision"] },
  { query: "artifacts_derived_from_input", label: "Artifacts derived from input", idLabel: "Input id", suggest: ["input"] },
  { query: "unused_references", label: "Unused references" },
  { query: "unmet_requirements", label: "Unmet requirements" },
  { query: "stale_artifacts", label: "Stale artifacts" },
  { query: "source_impact", label: "Source impact", idLabel: "Source id", suggest: ["source", "evidence", "input"] },
  { query: "requirement_coverage", label: "Requirement coverage" },
];

const ALL = "__all__";
// Node ids are `<document>/<kind>/<key>`.
const documentOf = (id: string) => id.split("/")[0] ?? "";
const kindOf = (id: string) => id.split("/")[1] ?? "";
const inDocument = (scope: string, id: string) => scope === ALL || documentOf(id) === scope;
const countsText = (coverage: Record<string, number> | undefined) => Object.entries(coverage ?? {}).map(([kind, count]) => `${count} ${kind}`).join(", ");

function Unavailable({ warnings }: { warnings?: string[] }) {
  return <Alert role="alert"><AlertTitle>The graph read model is unavailable</AlertTitle><AlertDescription>
    {warnings?.length ? warnings.map(warning => <p key={warning}>{warning}</p>) : <p>No reason was reported.</p>}</AlertDescription></Alert>;
}

function NoData({ coverage }: { coverage?: Record<string, number> }) {
  return <Alert role="status"><AlertTitle>No data to check</AlertTitle><AlertDescription>
    <p>This query had nothing to look at{coverage ? ` (${countsText(coverage)})` : ""}, so it cannot say whether anything is wrong. Run the pipeline so claims, sources, and artifacts exist, then run it again.</p></AlertDescription></Alert>;
}

function Nothing({ coverage }: { coverage?: Record<string, number> }) {
  return <div className="grid gap-1 text-sm" role="status">
    <p className="font-medium">Nothing found: no items match this query.</p>
    {coverage && <p className="text-muted-foreground">Checked {countsText(coverage)}.</p>}
  </div>;
}

function CoverageTable({ rows }: { rows: SectionCoverage[] }) {
  return <Table aria-label="Requirement coverage">
    <TableHeader><TableRow><TableHead>Section</TableHead><TableHead>Satisfied</TableHead><TableHead>Missing</TableHead></TableRow></TableHeader>
    <TableBody>{rows.map(row => <TableRow key={row.section.id}>
      <TableCell className="font-medium">{row.section.label}</TableCell>
      <TableCell className="whitespace-normal">{row.satisfied.length ? <ul>{row.satisfied.map(item => <li key={item.id}>{item.label}</li>)}</ul> : "-"}</TableCell>
      <TableCell className="whitespace-normal">{row.missing.length ? <ul>{row.missing.map(item => <li key={item.id}>{item.label}</li>)}</ul> : "-"}</TableCell>
    </TableRow>)}</TableBody>
  </Table>;
}

function QueryResults({ result, scope }: { result: GraphQueryResult; scope: string }) {
  if (result.graphUnavailable) return <Unavailable warnings={result.warnings} />;
  if (result.noData) return <NoData coverage={result.coverage} />;
  const items = result.items.filter(item => inDocument(scope, item.id));
  const sections = result.sections?.filter(row => inDocument(scope, row.section.id));
  if (sections) return sections.length === 0 ? <Nothing coverage={result.coverage} /> : <CoverageTable rows={sections} />;
  if (items.length === 0) return <Nothing coverage={result.coverage} />;
  return <Table aria-label="Query results">
    <TableHeader><TableRow><TableHead>Id</TableHead><TableHead>Kind</TableHead><TableHead>Label</TableHead><TableHead>Confidence</TableHead><TableHead>Attributes</TableHead></TableRow></TableHeader>
    <TableBody>{items.map(item => <TableRow key={item.id}>
      <TableCell className="font-medium">{item.id}</TableCell><TableCell>{item.kind}</TableCell><TableCell className="whitespace-normal">{item.label}</TableCell>
      <TableCell>{item.confidence === undefined ? "-" : `${Math.round(item.confidence * 100)}%`}</TableCell>
      <TableCell className="whitespace-normal">{scalarRows(item.attributes ?? {}).map(([key, value]) => `${key}: ${value}`).join("; ") || "-"}</TableCell>
    </TableRow>)}</TableBody>
  </Table>;
}

export function GraphPanel({ workspaceId }: { workspaceId: string | null }) {
  const api = useApi();
  const { t } = useT();
  const [selected, setSelected] = useState<GraphQuery>("claims_without_evidence");
  const [id, setId] = useState("");
  const [missing, setMissing] = useState("");
  const [scope, setScope] = useState(ALL);
  const graph = useQuery({ queryKey: reviewKeys.graph(workspaceId), queryFn: () => api.getGraph() });
  const run = useMutation({ mutationFn: () => api.getGraphQuery(selected, id.trim() || undefined) });
  const option = queries.find(item => item.query === selected)!;
  const nodes = graph.data?.nodes ?? [];
  const documents = [...new Set(nodes.map(node => documentOf(node.id)).filter(Boolean))].sort();
  const suggestions = nodes.filter(node => option.suggest?.includes(kindOf(node.id)) && inDocument(scope, node.id));
  const start = () => {
    if (option.idLabel && !id.trim()) { setMissing(`${option.idLabel} is required for this query.`); return; }
    setMissing(""); run.mutate();
  };
  return <div className="grid gap-6">
    <section aria-label="Graph overview" className="grid gap-2">
      <h2 className="text-xl font-semibold">Graph</h2>
      <QueryBoundary query={graph} title="Could not load the graph" skeleton="h-16 w-full">{data => data.unavailable
        ? <Unavailable warnings={data.warnings} />
        : data.nodes.length === 0
        ? <EmptyState title="The semantic graph is empty" description="Claims, sources, and artifacts are linked here once a run has produced evidence. Run the pipeline, then come back." action={{ label: t("empty.runPipeline"), to: "/pipeline" }} />
        : <p className="text-sm">{data.nodes.length} nodes and {data.edges.length} links connect claims, sources, sections, and artifacts.</p>}</QueryBoundary>
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
        <div className="grid gap-1"><Label htmlFor="graph-document">Document</Label>
          <Select value={scope} onValueChange={setScope}>
            <SelectTrigger id="graph-document" aria-label="Document" className="w-48"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={ALL}>All documents</SelectItem>{documents.map(name => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent>
          </Select></div>
        {option.idLabel && <div className="grid gap-1"><Label htmlFor="graph-query-id">{option.idLabel}</Label>
          <Input id="graph-query-id" className="w-72" list="graph-query-ids" value={id} onChange={event => setId(event.target.value)} />
          <datalist id="graph-query-ids">{suggestions.map(node => <option key={node.id} value={node.id} />)}</datalist></div>}
        <Button type="button" disabled={run.isPending} onClick={start}>Run query</Button>
      </div>
      {missing && <p className="text-sm text-destructive" role="alert">{missing}</p>}
      {run.isError && <ErrorState title="Could not run the query" message={formatApiError(run.error)} onRetry={start} retrying={run.isPending} />}
      {run.data && <QueryResults result={run.data} scope={scope} />}
    </section>
  </div>;
}
