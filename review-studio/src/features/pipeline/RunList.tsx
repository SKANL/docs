import { focusTargets } from "@/lib/focus-targets";
import { useT } from "@/lib/i18n";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState, focusById } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCapability } from "@/lib/capability-registry";
import { statusKey } from "@/lib/i18n";
import { Unavailable } from "@/components/shared/Unavailable";
import { isTerminalStatus } from "@/api/domains/pipeline";
import { RunStatusBadge } from "@/components/shared/StatusBadge";

const statuses = ["all", "queued", "running", "succeeded", "failed", "cancelled"];
const PAGE_SIZE = 20;
const REFRESH_MS = 5_000;

const when = (iso?: string) => { const date = iso ? new Date(iso) : null; return date && !Number.isNaN(date.getTime()) ? date.toLocaleString() : "-"; };

export function RunList({ workspaceId }: { workspaceId: string | null }) {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const [status, setStatus] = useState("all");
  const [documentText, setDocumentText] = useState("");
  const [documentId, setDocumentId] = useState("");
  // ponytail: a free-text document filter (debounced); a picker over listDocuments if workspaces grow large.
  useEffect(() => { const timer = setTimeout(() => setDocumentId(documentText.trim()), 300); return () => clearTimeout(timer); }, [documentText]);

  const runs = useInfiniteQuery({
    queryKey: ["pipeline", workspaceId, "runs", status, documentId],
    queryFn: ({ pageParam }) => api.listRunPage!({ status: status === "all" ? undefined : status, documentId: documentId || undefined, cursor: pageParam, limit: PAGE_SIZE }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: last => last.nextCursor,
    enabled: !!api.listRunPage && can("run.list"),
    // Keep a live view of work in flight; a settled list stops polling.
    refetchInterval: query => query.state.data?.pages.some(page => page.items.some(item => !isTerminalStatus(item.status))) ? REFRESH_MS : false,
  });
  const items = runs.data?.pages.flatMap(page => page.items) ?? [];

  return <section aria-label={t("pl.history")} className="grid gap-4">
    <h2 className="text-xl font-semibold">{t("pl.runs")}</h2>
    {!can("run.list") || !api.listRunPage ? <Unavailable>{t("pl.historyUnavailable")}</Unavailable> : <>
      <div className="flex flex-wrap items-end gap-4">
        <div className="grid gap-1"><Label htmlFor="run-status">{t("pl.status")}</Label>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger id="run-status" aria-label={t("pl.status")} className="w-40"><SelectValue /></SelectTrigger>
            <SelectContent>{statuses.map(value => <SelectItem key={value} value={value}>{t(statusKey("run.status", value) ?? "run.status.all")}</SelectItem>)}</SelectContent>
          </Select></div>
        <div className="grid gap-1"><Label htmlFor="run-document">{t("pl.document")}</Label>
          <Input id="run-document" className="w-56" value={documentText} onChange={event => setDocumentText(event.target.value)} /></div>
      </div>
      <QueryBoundary query={runs}>{() => items.length === 0 ? <EmptyState title={t("pl.none.title")} description={t("pl.none.body")} action={{ label: t("empty.planRun"), onClick: focusById(focusTargets.runPipeline) }} />
        : <>
          <Table aria-label={t("pl.runs")}>
            <TableHeader><TableRow><TableHead>{t("pl.runCol")}</TableHead><TableHead>{t("pl.document")}</TableHead><TableHead>{t("pl.status")}</TableHead><TableHead>{t("pl.formatCol")}</TableHead><TableHead>{t("pl.startedCol")}</TableHead></TableRow></TableHeader>
            <TableBody>{items.map(item => <TableRow key={item.id}>
              <TableCell><Link className="font-medium underline-offset-4 hover:underline" to={`/pipeline/runs/${encodeURIComponent(item.id)}`}>{item.id}</Link></TableCell>
              <TableCell>{item.documentId ?? "-"}</TableCell>
              <TableCell><RunStatusBadge status={item.status} /></TableCell>
              <TableCell>{item.format ?? "-"}</TableCell>
              <TableCell>{when(item.createdAt)}</TableCell>
            </TableRow>)}</TableBody>
          </Table>
          {runs.hasNextPage && <Button type="button" variant="outline" className="w-fit" disabled={runs.isFetchingNextPage} onClick={() => void runs.fetchNextPage()}>{t("pl.loadMore")}</Button>}
        </>}</QueryBoundary>
    </>}
  </section>;
}
