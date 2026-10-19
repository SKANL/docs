import { formatApiError } from "@/api/errors";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { GlossaryHint } from "@/components/shared/GlossaryHint";
import { PageHeader } from "@/components/shared/PageHeader";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveContext, type ActiveContext } from "@/app/active-context";
import { useMode, type Mode } from "@/app/mode";
import { RunStatusBadge } from "@/components/shared/StatusBadge";
import { useT, type MessageKey } from "@/lib/i18n";
import type { GlossaryTerm } from "@/lib/i18n/glossary";
import { toFindingRow } from "../review/data";

// ponytail: findings are matched to the document through its latest 100 runs (the API has no document filter for findings); a count that cannot cover them all is shown as partial. A server-side filter would lift the cap.
const RUN_WINDOW = 100;
const RECENT = 5;

/** Two cards, shown until the person picks how they work. Choosing is remembered and can be changed from the top bar. */
function ModeChooser() {
  const { t } = useT();
  const { setMode } = useMode();
  const cards: Array<[Mode, MessageKey, MessageKey]> = [["supervise", "mode.supervise", "home.choose.supervise"], ["write", "mode.write", "home.choose.write"]];
  return <div role="group" aria-label={t("home.choose.title")} className="grid gap-3 rounded-lg border bg-card p-4">
    <h2 className="text-lg font-semibold">{t("home.choose.title")}</h2>
    <div className="grid gap-3 sm:grid-cols-2">{cards.map(([mode, title, body]) =>
      <button key={mode} type="button" onClick={() => setMode(mode)} className="grid gap-1 rounded-md border p-4 text-left hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
        <span className="font-semibold">{t(title)}</span><span className="text-sm text-muted-foreground">{t(body)}</span>
      </button>)}</div>
    <p className="text-sm text-muted-foreground">{t("home.choose.hint")}</p>
  </div>;
}

/** Sources, then write or run, then review, then deliver. Plain links: URL routes stay valid whichever areas the nav shows. */
function Flow() {
  const { t } = useT();
  const { mode } = useMode();
  const steps: Array<[string, string, GlossaryTerm | null]> = [
    [t("home.step.sources"), "/authoring/sources", "source"],
    mode === "write" ? [t("home.step.write"), "/authoring/sections", null] : [t("term.run"), "/pipeline", "run"],
    [t("home.step.review"), "/review/findings", "finding"],
    [t("term.deliver"), "/delivery", "deliver"],
  ];
  return <ol aria-label={t("home.flow")} className="grid gap-2 sm:grid-cols-4">
    {steps.map(([label, to, term], index) => <li key={to} className="flex items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm">
      <span aria-hidden="true" className="text-muted-foreground">{index + 1}</span>
      <Link className="font-medium underline-offset-4 hover:underline" to={to}>{label}</Link>
      {term && <GlossaryHint term={term} />}
    </li>)}
  </ol>;
}

function HomeView({ header, context }: { header: ReactNode; context: ActiveContext }) {
  const api = useApi();
  const { t } = useT();
  const { hasChosenMode } = useMode();
  const { documentId, workspaceId } = context;
  const key = ["home", workspaceId, documentId];
  const status = useQuery({ queryKey: [...key, "status"], queryFn: () => api.getDocumentStatus!(documentId!, workspaceId ?? undefined), enabled: !!documentId && !!api.getDocumentStatus });
  const sources = useQuery({ queryKey: [...key, "sources"], queryFn: () => api.listSources!(documentId!), enabled: !!documentId && !!api.listSources });
  const runs = useQuery({ queryKey: [...key, "runs"], queryFn: () => api.listRunPage!({ documentId: documentId!, limit: RUN_WINDOW }), enabled: !!documentId && !!api.listRunPage });
  const findings = useQuery({ queryKey: [...key, "findings"], queryFn: () => api.listFindings(), enabled: !!documentId });

  const blockers = Array.isArray(status.data?.publication_blockers) ? status.data.publication_blockers : [];
  const allRuns = runs.data?.items ?? [];
  const recent = allRuns.slice(0, RECENT);
  // The API lists findings per workspace only, so they are matched to this document through its runs.
  const runIds = new Set(allRuns.map(item => item.id));
  const rows = (findings.data ?? []).map(toFindingRow);
  const mine = rows.filter(item => item.runId !== undefined && runIds.has(item.runId));
  const failing = mine.filter(item => item.status === "failed").length;
  // Findings with no run, or runs beyond the window, cannot be matched to this document: the count is then a lower bound, never a fact.
  const partial = rows.some(item => item.runId === undefined) || !!runs.data?.nextCursor;
  // "source" is not an asset kind (the server rejects it); the server's source inventory covers inbox files
  // and ingested outputs, so a source that was just added counts before it is ingested.
  // A failed or still-loading query is unknown, never evidence: suggest no step inferred from it.
  const unknown = [sources, runs, findings].some(query => query.isError || (query.isPending && query.fetchStatus !== "idle"));
  const next: [string, string] | null =
    !workspaceId ? ["/configure/workspaces", t("home.next.createWorkspace")]
    : !documentId ? ["/configure/workspaces", t("home.next.createDocument")]
    : unknown ? null
    : sources.data && sources.data.items.length === 0 ? ["/authoring/sources", t("home.next.uploadSources")]
    : runs.data && !allRuns.some(item => item.status === "succeeded") ? ["/pipeline", t("home.next.run")]
    : failing > 0 ? ["/review/findings", t("home.next.review")]
    : runs.data ? ["/delivery", t("home.next.deliver")] : null;

  return <div className="grid gap-6">
    {header}
    {!hasChosenMode && <ModeChooser />}
    {next && <section aria-label={t("home.next")} className="grid gap-2">
      <h2 className="text-lg font-semibold">{t("home.next")}</h2>
      <Button asChild className="w-fit"><Link to={next[0]}>{next[1]}</Link></Button>
    </section>}
    <Flow />
    <section aria-label={t("home.readiness")} className="grid gap-2 rounded-lg border bg-card p-4">
      {documentId ? <>
        <h2 className="text-xl font-semibold">{context.documentTitle || documentId}</h2>
        <p className="text-sm text-muted-foreground">{context.workspaceName} · {documentId}</p>
        {status.isError ? <p role="alert" className="text-sm text-destructive">{formatApiError(status.error)}</p>
          : status.data ? <Badge variant="outline" className={status.data.succeeded === true ? "w-fit border-success/40 text-success" : "w-fit border-warning/50 text-warning"}>{status.data.succeeded === true ? t("home.ready") : t("home.attention")}</Badge>
          : <Skeleton className="h-5 w-24" />}
      </> : <p className="text-sm text-muted-foreground">{t(workspaceId ? "home.noDocument" : "home.noWorkspace")}</p>}
    </section>
    {documentId && <>
      <section aria-label={t("home.blockers")} className="grid gap-2">
        <h2 className="text-lg font-semibold">{t("home.blockers")}</h2>
        {blockers.length ? <ul className="list-disc pl-5 text-sm text-destructive">{blockers.map((blocker, index) => <li key={index}>{typeof blocker === "string" ? blocker : String((blocker as { message?: unknown }).message ?? t("home.blocked"))}</li>)}</ul>
          : <p className="text-sm text-muted-foreground">{t("home.noBlockers")}</p>}
        {findings.data && (runs.data || !api.listRunPage) && <p className="flex items-center gap-1 text-sm text-muted-foreground">{!runs.data ? t("home.findings.unavailable") : partial ? t("home.findings.partial", { count: failing, window: RUN_WINDOW }) : t(failing === 1 ? "home.findings.one" : "home.findings.other", { count: failing })}<GlossaryHint term="finding" /></p>}
        {sources.isError && <ErrorState message={formatApiError(sources.error)} onRetry={() => void sources.refetch()} />}
        {findings.isError && <ErrorState message={formatApiError(findings.error)} onRetry={() => void findings.refetch()} />}
      </section>
      <section aria-label={t("home.recent")} className="grid gap-2">
        <h2 className="text-lg font-semibold">{t("home.recent")}</h2>
        {runs.isError ? <ErrorState message={formatApiError(runs.error)} onRetry={() => void runs.refetch()} />
          : recent.length ? <ul className="grid gap-1">{recent.map(item => <li key={item.id} className="flex items-center gap-3 text-sm"><Link className="underline underline-offset-4" to={`/pipeline/runs/${encodeURIComponent(item.id)}`}>{item.id}</Link><RunStatusBadge status={item.status} /></li>)}</ul>
          : runs.data && <EmptyState title={t("home.noRuns.title")} description={t("home.noRuns.body")} action={{ label: t("empty.runPipeline"), to: "/pipeline" }} />}
      </section>
    </>}
  </div>;
}

/** Only server data and its presence; readiness and blockers are shown exactly as the server reports them. */
export function HomePage() {
  const active = useActiveContext();
  const { t } = useT();
  const header = <PageHeader title={t("nav.home")} description={t("home.purpose")} />;
  return <QueryBoundary query={active} header={header}>{context => <HomeView header={header} context={context} />}</QueryBoundary>;
}
