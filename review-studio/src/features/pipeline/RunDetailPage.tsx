import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useApi } from "@/app/providers";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { ErrorState } from "@/components/shared/ErrorState";
import { PageHeader } from "@/components/shared/PageHeader";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useAction } from "@/lib/actions";
import { statusKey, useT } from "@/lib/i18n";
import { useActiveContext } from "@/app/active-context";
import { useCapability } from "@/lib/capability-registry";
import { isTerminalStatus, toRunRecord } from "@/api/domains/pipeline";
import { RunStatusBadge } from "@/components/shared/StatusBadge";
import { useRunStream } from "./useRunStream";

const POLL_MS = 2_000;

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const active = useActiveContext();
  const workspaceId = active.data?.workspaceId ?? null;
  const [confirmCancel, setConfirmCancel] = useState(false);

  const recordKey = ["pipeline", workspaceId, "run", runId];
  const listKey = ["pipeline", workspaceId, "runs"];
  const record = useQuery({
    queryKey: recordKey,
    queryFn: async () => toRunRecord(await api.getRun!(runId)),
    enabled: !!api.getRun && active.isSuccess,
    // Without a progress stream the record itself is polled until it settles.
    refetchInterval: query => !api.streamProgress && query.state.data && !isTerminalStatus(query.state.data.status) ? POLL_MS : false,
  });
  const settled = isTerminalStatus(record.data?.status);
  const stream = useRunStream(runId, { workspaceId, enabled: !!record.data && !settled });

  const refresh = () => { void queryClient.invalidateQueries({ queryKey: recordKey }); void queryClient.invalidateQueries({ queryKey: listKey }); };
  // The stream's closing frame says the run ended; refetch the stored record and the lists once.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (stream.terminal) refresh(); }, [stream.terminal, runId, workspaceId]);

  const cancel = useAction(() => api.cancelRun!(runId), { success: () => t("pl.cancelling", { id: runId }), onDone: () => { setConfirmCancel(false); refresh(); } });
  const retry = useAction(() => api.retryRun!(runId), { success: result => t("pl.retrying", { id: String(result.id ?? "") }), onDone: result => { refresh(); if (result.id) navigate(`/pipeline/runs/${encodeURIComponent(String(result.id))}`); } });

  const back = <Button asChild variant="link" className="h-auto w-fit p-0"><Link to="/pipeline">{t("pl.back")}</Link></Button>;
  const title = t("pl.runTitle", { id: runId });
  const header = <>{back}<PageHeader eyebrow={t("pl.title")} title={title} /></>;
  return <QueryBoundary query={record} title={t("pl.loadFailed")} skeleton="h-32 w-full" header={header}>{data => {
    const status = settled ? data.status : stream.status ?? data.status;
    const done = isTerminalStatus(status);
    const percent = stream.percent ?? data.percent ?? (status === "succeeded" ? 100 : 0);
    const message = stream.message ?? (data.stage ? `${data.stage}: ${data.percent ?? 0}%` : undefined);
    const facts: Array<[string, string | undefined]> = [[t("pl.fact.document"), data.documentId], [t("pl.fact.format"), data.format], [t("pl.fact.policy"), data.policy], [t("pl.fact.pipeline"), data.pipelineId], [t("pl.fact.started"), data.createdAt]];
    const statusText = (word: string) => { const key = statusKey("run.status", word); return key ? t(key) : word; };

    return <div className="grid gap-6">
      {back}
      <PageHeader eyebrow={t("pl.title")} title={title} actions={<>
        {!done && can("run.cancel") && api.cancelRun && <Button type="button" variant="outline" onClick={() => setConfirmCancel(true)}>{t("pl.cancelRun")}</Button>}
        {done && status !== "succeeded" && can("run.retry") && api.retryRun && <Button type="button" disabled={retry.isPending} onClick={() => retry.mutate(undefined)}>{t("pl.retry")}</Button>}
      </>} />
      <section aria-label={t("pl.summary")} className="grid gap-3 rounded-lg border bg-card p-4 text-sm">
        <div className="flex items-center gap-2"><span className="text-muted-foreground">{t("pl.status")}</span> <RunStatusBadge status={status} /></div>
        <dl className="grid gap-x-8 gap-y-1 sm:grid-cols-2">{facts.filter(([, value]) => value).map(([label, value]) => <div key={label} className="flex gap-2"><dt className="text-muted-foreground">{label}</dt><dd>{value}</dd></div>)}</dl>
        <Progress value={percent} aria-label={t("pl.progress")} aria-valuenow={percent} />
        {message && <p className="text-muted-foreground" role="status">{message}</p>}
        {stream.error && !done && <p className="text-destructive" role="status">{t("pl.connectionLost", { error: stream.error })}</p>}
      </section>
      {done && <section aria-label={t("pl.receiptLabel")} className="grid gap-2 rounded-lg border bg-card p-4 text-sm">
        <h2 className="text-lg font-semibold">{t("pl.receipt")}</h2>
        <p>{t("pl.finalStatus")} <b>{statusText(status)}</b></p>
        <Button asChild variant="link" className="h-auto w-fit p-0"><Link to={`/review/evidence/${encodeURIComponent(runId)}`}>{t("pl.reviewEvidence")}</Link></Button>
      </section>}
      {retry.isError && <ErrorState title={t("pl.retryFailed")} error={retry.error} onRetry={() => retry.mutate(undefined)} retrying={retry.isPending} />}
      <ConfirmActionDialog open={confirmCancel} onOpenChange={setConfirmCancel} title={t("pl.cancelTitle")} description={t("pl.cancelBody")}
        confirmLabel={t("pl.cancelConfirm")} pending={cancel.isPending} error={cancel.error} onConfirm={() => cancel.mutate(undefined)} />
    </div>;
  }}</QueryBoundary>;
}
