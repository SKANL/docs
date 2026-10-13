import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { ErrorState } from "@/components/shared/ErrorState";
import { PageHeader } from "@/components/shared/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorText, useActiveContext } from "@/features/authoring/data";
import { RunStatusBadge } from "@/features/pipeline/RunStatusBadge";

const none = <p className="text-sm text-muted-foreground">Nothing reported yet.</p>;

/** Only server data and its presence; readiness and blockers are shown exactly as the server reports them. */
export function HomePage() {
  const api = useApi();
  const active = useActiveContext();
  const documentId = active.data?.documentId ?? null;
  const workspaceId = active.data?.workspaceId ?? null;
  const key = ["home", workspaceId, documentId];
  const status = useQuery({ queryKey: [...key, "status"], queryFn: () => api.getDocumentStatus!(documentId!, workspaceId ?? undefined), enabled: !!documentId && !!api.getDocumentStatus });
  const sources = useQuery({ queryKey: [...key, "sources"], queryFn: () => api.getDocumentClassification!(documentId!), enabled: !!documentId && !!api.getDocumentClassification });
  const runs = useQuery({ queryKey: [...key, "runs"], queryFn: () => api.listRunPage!({ documentId: documentId!, limit: 5 }), enabled: !!documentId && !!api.listRunPage });
  const findings = useQuery({ queryKey: [...key, "findings"], queryFn: () => api.listFindings(), enabled: !!documentId });

  const header = <PageHeader eyebrow="Task area" title="Home" description="Current document readiness, blockers, recent runs, and the next safe action." />;
  if (active.isPending) return <div className="grid gap-6">{header}<Skeleton className="h-24 w-full" /></div>;
  if (active.isError) return <div className="grid gap-6">{header}<ErrorState message={errorText(active.error, "workspace")} onRetry={() => void active.refetch()} /></div>;

  const blockers = Array.isArray(status.data?.publication_blockers) ? status.data.publication_blockers : [];
  const recent = runs.data?.items ?? [];
  const failing = (findings.data ?? []).filter(item => item.status === "failed").length;
  // "source" is not an asset kind (the server rejects it); ingested sources are the classification items.
  // A failed or still-loading query is unknown, never evidence: suggest no step inferred from it.
  const unknown = [sources, runs, findings].some(query => query.isError || (query.isPending && query.fetchStatus !== "idle"));
  const next: [string, string] | null =
    !documentId ? ["/configure/workspaces", "Create a document"]
    : unknown ? null
    : sources.data && sources.data.items.length === 0 ? ["/authoring/sources", "Add sources"]
    : runs.data && !recent.some(item => item.status === "succeeded") ? ["/pipeline", "Run the pipeline"]
    : failing > 0 ? ["/review/findings", "Review findings"]
    : runs.data ? ["/delivery", "Continue to delivery"] : null;

  return <div className="grid gap-6">
    {header}
    <section aria-label="Document readiness" className="grid gap-2 rounded-lg border bg-card p-4">
      {documentId ? <>
        <h2 className="text-xl font-semibold">{active.data!.documentTitle || documentId}</h2>
        <p className="text-sm text-muted-foreground">{active.data!.workspaceName} · {documentId}</p>
        {status.isError ? <p role="alert" className="text-sm text-destructive">{errorText(status.error, "status")}</p>
          : status.data ? <Badge variant="outline" className={status.data.succeeded === true ? "w-fit border-success/40 text-success" : "w-fit border-warning/50 text-warning"}>{status.data.succeeded === true ? "Ready" : "Needs attention"}</Badge>
          : <Skeleton className="h-5 w-24" />}
      </> : <p className="text-sm text-muted-foreground">No document is selected for this workspace.</p>}
    </section>
    <section aria-label="Blockers" className="grid gap-2">
      <h2 className="text-lg font-semibold">Blockers</h2>
      {blockers.length ? <ul className="list-disc pl-5 text-sm text-destructive">{blockers.map((blocker, index) => <li key={index}>{typeof blocker === "string" ? blocker : String((blocker as { message?: unknown }).message ?? "Blocked")}</li>)}</ul> : none}
      {/* ponytail: the server cannot filter findings by document, so the count is workspace-wide and says so. */}
      {findings.data && <p className="text-sm text-muted-foreground">{failing} failing {failing === 1 ? "finding" : "findings"} of {findings.data.length} reported in this workspace.</p>}
      {sources.isError && <ErrorState message={errorText(sources.error, "sources")} onRetry={() => void sources.refetch()} />}
      {findings.isError && <ErrorState message={errorText(findings.error, "findings")} onRetry={() => void findings.refetch()} />}
    </section>
    <section aria-label="Recent runs" className="grid gap-2">
      <h2 className="text-lg font-semibold">Recent runs</h2>
      {runs.isError ? <ErrorState message={errorText(runs.error, "runs")} onRetry={() => void runs.refetch()} />
        : recent.length ? <ul className="grid gap-1">{recent.map(item => <li key={item.id} className="flex items-center gap-3 text-sm"><Link className="underline underline-offset-4" to={`/pipeline/runs/${encodeURIComponent(item.id)}`}>{item.id}</Link><RunStatusBadge status={item.status} /></li>)}</ul> : none}
    </section>
    {next && <section aria-label="Next safe action"><Button asChild><Link to={next[0]}>{next[1]}</Link></Button></section>}
  </div>;
}
