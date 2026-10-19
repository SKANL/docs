import { focusTargets } from "@/lib/focus-targets";
import { useT } from "@/lib/i18n";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState, focusById } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Unavailable } from "@/components/shared/Unavailable";
import { useCapability } from "@/lib/capability-registry";
import { CopyDigest, deliveryKeys } from "./data";

const when = (iso?: string) => { const date = iso ? new Date(iso) : null; return date && !Number.isNaN(date.getTime()) ? date.toLocaleString() : "-"; };

/** What the server recorded. A policy or warnings column shows "-" when the record does not carry them; it never guesses. */
export function PublicationHistory({ workspaceId }: { workspaceId: string | null }) {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const canPublish = can("document.publish") && !!api.publishDocument;
  const listed = !!api.listPublicationHistory && can("publications.list");
  const history = useQuery({ queryKey: deliveryKeys.publications(workspaceId), queryFn: () => api.listPublicationHistory!(), enabled: listed });
  return <section aria-label={t("dl.hist.heading")} className="grid gap-4">
    <h2 className="text-xl font-semibold">{t("dl.hist.heading")}</h2>
    {!listed ? <Unavailable>{t("dl.hist.unavailable")}</Unavailable>
      : <QueryBoundary query={history}>{records => records.length === 0 ? <EmptyState title={t("dl.hist.none.title")} description={t("dl.hist.none.body")} action={canPublish ? { label: t("empty.publish"), onClick: focusById(focusTargets.publishDocument) } : undefined} />
      : <Table aria-label={t("dl.hist.heading")}>
        <TableHeader><TableRow><TableHead>{t("dl.hist.publication")}</TableHead><TableHead>{t("dl.pub.destination")}</TableHead><TableHead>{t("dl.policy")}</TableHead><TableHead>{t("dl.artifactDigest")}</TableHead><TableHead>{t("dl.evidenceRun")}</TableHead><TableHead>{t("dl.hist.published")}</TableHead><TableHead>{t("dl.hist.warnings")}</TableHead></TableRow></TableHeader>
        <TableBody>{records.map(item => <TableRow key={item.id}>
          <TableCell className="font-medium">{item.id}</TableCell>
          <TableCell className="break-all">{item.destination || "-"}</TableCell>
          <TableCell>{item.policy ?? "-"}</TableCell>
          <TableCell><CopyDigest value={item.artifactSha256} /></TableCell>
          <TableCell>{item.runId ? <Link className="underline-offset-4 hover:underline" to={`/review/evidence/${encodeURIComponent(item.runId)}`}>{item.runId}</Link> : "-"}</TableCell>
          <TableCell>{when(item.publishedAt)}</TableCell>
          <TableCell>{item.warnings.length ? item.warnings.join("; ") : "-"}</TableCell>
        </TableRow>)}</TableBody>
      </Table>}</QueryBoundary>}
  </section>;
}
