import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { useMode } from "@/app/mode";
import { GlossaryHint } from "@/components/shared/GlossaryHint";
import { EmptyState } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Unavailable } from "@/components/shared/Unavailable";
import { useCapability } from "@/lib/capability-registry";
import type { EvidenceBundle } from "@/api/domains/review";
import { RunStatusBadge } from "@/components/shared/StatusBadge";
import { useT } from "@/lib/i18n";
import { BaselinePromotionDialog } from "./BaselinePromotionDialog";
import { Digest, Facts } from "@/components/shared/Facts";
import { SeverityBadge, reviewKeys, toFindingRow } from "./data";

const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" ? value as Record<string, unknown> : {};
const count = (value: unknown) => Array.isArray(value) ? value.length : 0;

/** Passport reduced to what a reviewer acts on: stage outcomes and retry lineage. Never the raw entries. */
function PassportSummary({ passport }: { passport: Record<string, unknown> }) {
  const { t } = useT();
  const entries = (Array.isArray(passport.entries) ? passport.entries : []).map(record);
  const stages = entries.filter(entry => entry.stage === "pipeline_stage");
  const worker = entries.find(entry => entry.stage === "worker");
  return <section aria-label={t("rv.ev.passportSummary")} className="grid gap-3 rounded-lg border bg-card p-4">
    <h3 className="flex items-center gap-1 text-lg font-semibold">{t("rv.ev.passport")}<GlossaryHint term="passport" /></h3>
    <p className="flex items-center gap-1 text-sm text-muted-foreground">{t(entries.length === 1 ? "rv.ev.attestations.one" : "rv.ev.attestations.other", { count: entries.length })}<GlossaryHint term="attestation" /></p>
    {typeof worker?.retry_of === "string" && <p className="text-sm" role="status">{t("rv.ev.retry", { attempt: String(worker.attempt ?? "-"), origin: worker.retry_of })}</p>}
    {stages.length > 0 && <ul className="grid gap-2" aria-label={t("rv.ev.stages")}>{stages.map((entry, index) => {
      const receipt = record(entry.receipt);
      return <li key={`${String(entry.name)}-${index}`} className="flex flex-wrap items-center gap-2 text-sm">
        <b>{String(entry.name ?? t("rv.ev.stage"))}</b><Badge variant={receipt.outcome === "passed" || receipt.outcome === "succeeded" ? "default" : "secondary"}>{String(receipt.outcome ?? t("rv.sev.unknown"))}</Badge>
        <span className="text-muted-foreground">{t("rv.ev.stageCounts", { artifacts: count(receipt.artifacts), warnings: count(receipt.warnings), errors: count(receipt.errors) })}</span>
      </li>;
    })}</ul>}
  </section>;
}

function EvidenceView({ workspaceId, runId, evidence }: { workspaceId: string | null; runId: string; evidence: EvidenceBundle }) {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const { advanced } = useMode();
  const [promoting, setPromoting] = useState(false);
  const findings = evidence.findings.map(toFindingRow);
  return <div className="grid gap-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-xl font-semibold">{t("rv.ev.for", { id: runId })}</h2>
      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline"><Link to={`/pipeline/runs/${encodeURIComponent(runId)}`}>{t("rv.ev.runDetails")}</Link></Button>
        {can("document.baseline") && api.promoteBaseline && <Button type="button" onClick={() => setPromoting(true)}>{t("rv.ev.promote")}</Button>}
      </div>
    </div>
    <section aria-label={advanced ? t("rv.ev.digestLabel") : t("rv.ev.summaryLabel")} className="grid gap-2 rounded-lg border bg-card p-4">
      <Facts rows={[[t("rv.ev.sha"), advanced ? <span key="d" className="inline-flex items-center gap-1"><Digest value={evidence.evidence_sha256} /><GlossaryHint term="digest" /></span> : undefined], [t("rv.ev.artifacts"), String(evidence.artifacts.length)], [t("rv.ev.findings"), String(findings.length)],
        [t("rv.ev.previews"), evidence.previews.available ? t("rv.ev.rendered", { count: evidence.previews.artifact_ids.length }) : t("rv.ev.noneRendered")]]} />
    </section>
    {advanced && <PassportSummary passport={evidence.passport} />}
    <section aria-label={t("rv.ev.artifacts")} className="grid gap-2">
      <h3 className="text-lg font-semibold">{t("rv.ev.artifacts")}</h3>
      {evidence.artifacts.length === 0 ? <p className="text-sm text-muted-foreground">{t("rv.ev.noArtifacts")}</p> : <Table aria-label={t("rv.ev.runArtifacts")}>
        <TableHeader><TableRow><TableHead>{t("rv.art.col")}</TableHead><TableHead>{t("rv.art.kind")}</TableHead><TableHead>{t("rv.ev.mediaType")}</TableHead>{advanced && <TableHead>{t("rv.ev.digest")}</TableHead>}</TableRow></TableHeader>
        <TableBody>{evidence.artifacts.map(item => <TableRow key={item.id}>
          <TableCell><Link className="font-medium underline-offset-4 hover:underline" to={`/review/artifacts/${encodeURIComponent(item.id)}`}>{item.id}</Link></TableCell>
          <TableCell>{item.kind}</TableCell><TableCell>{item.media_type || "-"}</TableCell>{advanced && <TableCell><Digest value={item.digest} /></TableCell>}
        </TableRow>)}</TableBody>
      </Table>}
    </section>
    <section aria-label={t("rv.ev.runFindings")} className="grid gap-2">
      <h3 className="text-lg font-semibold">{t("rv.ev.findings")}</h3>
      {findings.length === 0 ? <p className="text-sm text-muted-foreground">{t("rv.ev.noFindings")}</p> : <ul className="grid gap-2">{findings.map(item => <li key={item.id} className="flex flex-wrap items-center gap-2 text-sm">
        <SeverityBadge severity={item.severity} /><Link className="font-medium underline underline-offset-4" to={`/review/findings/${encodeURIComponent(item.id)}`}>{item.id}</Link><span>{item.message || t("rv.noDescription")}</span>
      </li>)}</ul>}
    </section>
    {promoting && <BaselinePromotionDialog workspaceId={workspaceId} runId={runId} onClose={() => setPromoting(false)} />}
  </div>;
}

export function EvidencePanel({ workspaceId, runId }: { workspaceId: string | null; runId?: string }) {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const available = can("document.evidence") && !!api.getRunEvidence;
  const evidence = useQuery({ queryKey: reviewKeys.evidence(workspaceId, runId ?? ""), queryFn: () => api.getRunEvidence!(runId!), enabled: !!runId && available });
  const runs = useQuery({ queryKey: reviewKeys.runs(workspaceId), queryFn: async () => (await api.listRunPage!()).items, enabled: !runId });

  if (!runId) return <QueryBoundary query={runs} title={t("rv.ev.runsLoadFailed")}>{list => list.length === 0
    ? <EmptyState title={t("rv.ev.noRuns.title")} description={t("rv.ev.noRuns.body")}><Button asChild><Link to="/pipeline">{t("rv.ev.openPipeline")}</Link></Button></EmptyState>
    : <section aria-label={t("rv.ev.runsWithEvidence")} className="grid gap-2">
      <h2 className="text-xl font-semibold">{t("rv.ev.choose")}</h2>
      <ul className="grid gap-1">{list.map(run => <li key={run.id} className="flex items-center gap-2 text-sm"><Link className="font-medium underline underline-offset-4" to={`/review/evidence/${encodeURIComponent(run.id)}`}>{run.id}</Link><RunStatusBadge status={run.status} /><span className="text-muted-foreground">{run.documentId}</span></li>)}</ul>
    </section>}</QueryBoundary>;
  if (!available) return <Unavailable>{t("rv.ev.unavailable")}</Unavailable>;
  return <QueryBoundary query={evidence} title={t("rv.ev.loadFailed")} skeleton="h-32 w-full">{bundle => <EvidenceView workspaceId={workspaceId} runId={runId} evidence={bundle} />}</QueryBoundary>;
}
