import { useT, type MessageKey } from "@/lib/i18n";
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
const queries: Array<{ query: GraphQuery; idLabel?: MessageKey; suggest?: string[] }> = [
  { query: "claims_without_evidence" },
  { query: "findings_affected_by_revision", idLabel: "rv.gr.revisionId", suggest: ["revision"] },
  { query: "artifacts_derived_from_input", idLabel: "rv.gr.inputId", suggest: ["input"] },
  { query: "unused_references" },
  { query: "unmet_requirements" },
  { query: "stale_artifacts" },
  { query: "source_impact", idLabel: "rv.gr.sourceId", suggest: ["source", "evidence", "input"] },
  { query: "requirement_coverage" },
];

const ALL = "__all__";
// Node ids are `<document>/<kind>/<key>`.
const documentOf = (id: string) => id.split("/")[0] ?? "";
const kindOf = (id: string) => id.split("/")[1] ?? "";
const inDocument = (scope: string, id: string) => scope === ALL || documentOf(id) === scope;
const countsText = (coverage: Record<string, number> | undefined) => Object.entries(coverage ?? {}).map(([kind, count]) => `${count} ${kind}`).join(", ");

function Unavailable({ warnings }: { warnings?: string[] }) {
  const { t } = useT();
  return <Alert role="alert"><AlertTitle>{t("rv.gr.unavailable")}</AlertTitle><AlertDescription>
    {warnings?.length ? warnings.map(warning => <p key={warning}>{warning}</p>) : <p>{t("rv.gr.noReason")}</p>}</AlertDescription></Alert>;
}

function NoData({ coverage }: { coverage?: Record<string, number> }) {
  const { t } = useT();
  return <Alert role="status"><AlertTitle>{t("rv.gr.noData")}</AlertTitle><AlertDescription>
    <p>{t("rv.gr.noDataBody", { coverage: coverage ? ` (${countsText(coverage)})` : "" })}</p></AlertDescription></Alert>;
}

function Nothing({ coverage }: { coverage?: Record<string, number> }) {
  const { t } = useT();
  return <div className="grid gap-1 text-sm" role="status">
    <p className="font-medium">{t("rv.gr.nothing")}</p>
    {coverage && <p className="text-muted-foreground">{t("rv.gr.checkedCoverage", { coverage: countsText(coverage) })}</p>}
  </div>;
}

function CoverageTable({ rows }: { rows: SectionCoverage[] }) {
  const { t } = useT();
  return <Table aria-label={t("rv.gr.requirement_coverage")}>
    <TableHeader><TableRow><TableHead>{t("rv.gr.section")}</TableHead><TableHead>{t("rv.gr.satisfied")}</TableHead><TableHead>{t("rv.gr.missing")}</TableHead></TableRow></TableHeader>
    <TableBody>{rows.map(row => <TableRow key={row.section.id}>
      <TableCell className="font-medium">{row.section.label}</TableCell>
      <TableCell className="whitespace-normal">{row.satisfied.length ? <ul>{row.satisfied.map(item => <li key={item.id}>{item.label}</li>)}</ul> : "-"}</TableCell>
      <TableCell className="whitespace-normal">{row.missing.length ? <ul>{row.missing.map(item => <li key={item.id}>{item.label}</li>)}</ul> : "-"}</TableCell>
    </TableRow>)}</TableBody>
  </Table>;
}

function QueryResults({ result, scope }: { result: GraphQueryResult; scope: string }) {
  const { t } = useT();
  if (result.graphUnavailable) return <Unavailable warnings={result.warnings} />;
  if (result.noData) return <NoData coverage={result.coverage} />;
  const items = result.items.filter(item => inDocument(scope, item.id));
  const sections = result.sections?.filter(row => inDocument(scope, row.section.id));
  if (sections) return sections.length === 0 ? <Nothing coverage={result.coverage} /> : <CoverageTable rows={sections} />;
  if (items.length === 0) return <Nothing coverage={result.coverage} />;
  return <Table aria-label={t("rv.gr.results")}>
    <TableHeader><TableRow><TableHead>{t("rv.gr.id")}</TableHead><TableHead>{t("rv.gr.kind")}</TableHead><TableHead>{t("rv.gr.label")}</TableHead><TableHead>{t("rv.gr.confidence")}</TableHead><TableHead>{t("rv.gr.attributes")}</TableHead></TableRow></TableHeader>
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
    if (option.idLabel && !id.trim()) { setMissing(t("rv.gr.required", { field: t(option.idLabel) })); return; }
    setMissing(""); run.mutate();
  };
  return <div className="grid gap-6">
    <section aria-label={t("rv.gr.overview")} className="grid gap-2">
      <h2 className="text-xl font-semibold">{t("rv.gr.heading")}</h2>
      <QueryBoundary query={graph} title={t("rv.gr.loadFailed")} skeleton="h-16 w-full">{data => data.unavailable
        ? <Unavailable warnings={data.warnings} />
        : data.nodes.length === 0
        ? <EmptyState title={t("rv.gr.empty.title")} description={t("rv.gr.empty.body")} action={{ label: t("empty.runPipeline"), to: "/pipeline" }} />
        : <p className="text-sm">{t("rv.gr.counts", { nodes: data.nodes.length, links: data.edges.length })}</p>}</QueryBoundary>
    </section>
    <section aria-label={t("rv.gr.queries")} className="grid gap-3 rounded-lg border bg-card p-4">
      <h3 className="text-lg font-semibold">{t("rv.gr.readOnly")}</h3>
      <p className="text-sm text-muted-foreground">{t("rv.gr.exploratory")}</p>
      <div className="flex flex-wrap items-end gap-4">
        <div className="grid gap-1"><Label htmlFor="graph-query">{t("rv.gr.query")}</Label>
          <Select value={selected} onValueChange={value => { setSelected(value as GraphQuery); setMissing(""); run.reset(); }}>
            <SelectTrigger id="graph-query" aria-label={t("rv.gr.query")} className="w-72"><SelectValue /></SelectTrigger>
            <SelectContent>{queries.map(item => <SelectItem key={item.query} value={item.query}>{t(`rv.gr.${item.query}`)}</SelectItem>)}</SelectContent>
          </Select></div>
        <div className="grid gap-1"><Label htmlFor="graph-document">{t("rv.gr.document")}</Label>
          <Select value={scope} onValueChange={setScope}>
            <SelectTrigger id="graph-document" aria-label={t("rv.gr.document")} className="w-48"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={ALL}>{t("rv.gr.allDocuments")}</SelectItem>{documents.map(name => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent>
          </Select></div>
        {option.idLabel && <div className="grid gap-1"><Label htmlFor="graph-query-id">{t(option.idLabel)}</Label>
          <Input id="graph-query-id" className="w-72" list="graph-query-ids" value={id} onChange={event => setId(event.target.value)} />
          <datalist id="graph-query-ids">{suggestions.map(node => <option key={node.id} value={node.id} />)}</datalist></div>}
        <Button type="button" disabled={run.isPending} onClick={start}>{t("rv.gr.run")}</Button>
      </div>
      {missing && <p className="text-sm text-destructive" role="alert">{missing}</p>}
      {run.isError && <ErrorState title={t("rv.gr.runFailed")} error={run.error} onRetry={start} retrying={run.isPending} />}
      {run.data && <QueryResults result={run.data} scope={scope} />}
    </section>
  </div>;
}
