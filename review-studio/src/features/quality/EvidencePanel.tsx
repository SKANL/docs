import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Unavailable, errorText, useCapability } from "@/features/authoring/data";
import type { EvidenceBundle } from "@/api/domains/review";
import { BaselinePromotionDialog } from "./BaselinePromotionDialog";
import { Digest, Facts, SeverityBadge, reviewKeys, toFindingRow } from "./data";

const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" ? value as Record<string, unknown> : {};
const count = (value: unknown) => Array.isArray(value) ? value.length : 0;

/** Passport reduced to what a reviewer acts on: stage outcomes and retry lineage. Never the raw entries. */
function PassportSummary({ passport }: { passport: Record<string, unknown> }) {
  const entries = (Array.isArray(passport.entries) ? passport.entries : []).map(record);
  const stages = entries.filter(entry => entry.stage === "pipeline_stage");
  const worker = entries.find(entry => entry.stage === "worker");
  return <section aria-label="Passport summary" className="grid gap-3 rounded-lg border bg-card p-4">
    <h3 className="text-lg font-semibold">Passport</h3>
    <p className="text-sm text-muted-foreground">{entries.length} attestation{entries.length === 1 ? "" : "s"} recorded for this run.</p>
    {typeof worker?.retry_of === "string" && <p className="text-sm" role="status">Retry attempt {String(worker.attempt ?? "-")} derived from run {worker.retry_of}.</p>}
    {stages.length > 0 && <ul className="grid gap-2" aria-label="Pipeline stages">{stages.map((entry, index) => {
      const receipt = record(entry.receipt);
      return <li key={`${String(entry.name)}-${index}`} className="flex flex-wrap items-center gap-2 text-sm">
        <b>{String(entry.name ?? "stage")}</b><Badge variant={receipt.outcome === "passed" || receipt.outcome === "succeeded" ? "default" : "secondary"}>{String(receipt.outcome ?? "unknown")}</Badge>
        <span className="text-muted-foreground">artifacts {count(receipt.artifacts)} · warnings {count(receipt.warnings)} · errors {count(receipt.errors)}</span>
      </li>;
    })}</ul>}
  </section>;
}

function EvidenceView({ workspaceId, runId, evidence }: { workspaceId: string | null; runId: string; evidence: EvidenceBundle }) {
  const api = useApi();
  const can = useCapability();
  const [promoting, setPromoting] = useState(false);
  const findings = evidence.findings.map(toFindingRow);
  return <div className="grid gap-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-xl font-semibold">Evidence for {runId}</h2>
      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline"><Link to={`/pipeline/runs/${encodeURIComponent(runId)}`}>Run details</Link></Button>
        {can("document.baseline") && api.promoteBaseline && <Button type="button" onClick={() => setPromoting(true)}>Promote to baseline</Button>}
      </div>
    </div>
    <section aria-label="Evidence digest" className="grid gap-2 rounded-lg border bg-card p-4">
      <Facts rows={[["Evidence SHA-256", <Digest key="d" value={evidence.evidence_sha256} />], ["Artifacts", String(evidence.artifacts.length)], ["Findings", String(findings.length)],
        ["Previews", evidence.previews.available ? `${evidence.previews.artifact_ids.length} rendered` : "None rendered, so a baseline cannot be promoted from this run"]]} />
    </section>
    <PassportSummary passport={evidence.passport} />
    <section aria-label="Artifacts" className="grid gap-2">
      <h3 className="text-lg font-semibold">Artifacts</h3>
      {evidence.artifacts.length === 0 ? <p className="text-sm text-muted-foreground">This run produced no artifacts.</p> : <Table aria-label="Run artifacts">
        <TableHeader><TableRow><TableHead>Artifact</TableHead><TableHead>Kind</TableHead><TableHead>Media type</TableHead><TableHead>Digest</TableHead></TableRow></TableHeader>
        <TableBody>{evidence.artifacts.map(item => <TableRow key={item.id}>
          <TableCell><Link className="font-medium underline-offset-4 hover:underline" to={`/review/artifacts/${encodeURIComponent(item.id)}`}>{item.id}</Link></TableCell>
          <TableCell>{item.kind}</TableCell><TableCell>{item.media_type || "-"}</TableCell><TableCell><Digest value={item.digest} /></TableCell>
        </TableRow>)}</TableBody>
      </Table>}
    </section>
    <section aria-label="Run findings" className="grid gap-2">
      <h3 className="text-lg font-semibold">Findings</h3>
      {findings.length === 0 ? <p className="text-sm text-muted-foreground">No findings were recorded for this run.</p> : <ul className="grid gap-2">{findings.map(item => <li key={item.id} className="flex flex-wrap items-center gap-2 text-sm">
        <SeverityBadge severity={item.severity} /><Link className="font-medium underline underline-offset-4" to={`/review/findings/${encodeURIComponent(item.id)}`}>{item.id}</Link><span>{item.message}</span>
      </li>)}</ul>}
    </section>
    {promoting && <BaselinePromotionDialog workspaceId={workspaceId} runId={runId} onClose={() => setPromoting(false)} />}
  </div>;
}

export function EvidencePanel({ workspaceId, runId }: { workspaceId: string | null; runId?: string }) {
  const api = useApi();
  const can = useCapability();
  const available = can("document.evidence") && !!api.getRunEvidence;
  const evidence = useQuery({ queryKey: reviewKeys.evidence(workspaceId, runId ?? ""), queryFn: () => api.getRunEvidence!(runId!), enabled: !!runId && available });
  const runs = useQuery({ queryKey: reviewKeys.runs(workspaceId), queryFn: () => api.listRuns(), enabled: !runId });

  if (!runId) {
    if (runs.isPending) return <Skeleton className="h-24 w-full" />;
    if (runs.isError) return <ErrorState title="Could not load runs" message={errorText(runs.error, "runs")} onRetry={() => void runs.refetch()} />;
    if (runs.data.length === 0) return <EmptyState title="No runs yet" description="Run the pipeline for a document; its evidence is collected when the run finishes."><Button asChild><Link to="/pipeline">Open pipeline</Link></Button></EmptyState>;
    return <section aria-label="Runs with evidence" className="grid gap-2">
      <h2 className="text-xl font-semibold">Choose a run</h2>
      <ul className="grid gap-1">{runs.data.map(run => <li key={run.id} className="flex items-center gap-2 text-sm"><Link className="font-medium underline underline-offset-4" to={`/review/evidence/${encodeURIComponent(run.id)}`}>{run.id}</Link><Badge variant="secondary">{run.status}</Badge><span className="text-muted-foreground">{run.document}</span></li>)}</ul>
    </section>;
  }
  if (!available) return <Unavailable>Run evidence is not available on this server.</Unavailable>;
  if (evidence.isPending) return <Skeleton className="h-32 w-full" />;
  if (evidence.isError) return <ErrorState title="Could not load the evidence" message={errorText(evidence.error, "evidence")} onRetry={() => void evidence.refetch()} />;
  return <EvidenceView workspaceId={workspaceId} runId={runId} evidence={evidence.data} />;
}
