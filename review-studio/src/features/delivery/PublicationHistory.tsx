import { formatApiError } from "@/api/errors";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Unavailable } from "@/components/shared/Unavailable";
import { useCapability } from "@/lib/capability-registry";
import { CopyDigest, deliveryKeys } from "./data";

const when = (iso?: string) => { const date = iso ? new Date(iso) : null; return date && !Number.isNaN(date.getTime()) ? date.toLocaleString() : "-"; };

/** What the server recorded. A policy or warnings column shows "-" when the record does not carry them; it never guesses. */
export function PublicationHistory({ workspaceId }: { workspaceId: string | null }) {
  const api = useApi();
  const can = useCapability();
  const listed = !!api.listPublicationHistory && can("publications.list");
  const history = useQuery({ queryKey: deliveryKeys.publications(workspaceId), queryFn: () => api.listPublicationHistory!(), enabled: listed });
  return <section aria-label="Publication history" className="grid gap-4">
    <h2 className="text-xl font-semibold">Publication history</h2>
    {!listed ? <Unavailable>Publication history is not available on this server.</Unavailable>
      : history.isPending ? <Skeleton className="h-24 w-full" />
      : history.isError ? <ErrorState message={formatApiError(history.error)} onRetry={() => void history.refetch()} />
      : history.data.length === 0 ? <EmptyState title="Nothing published yet" description="Publications the server accepts are recorded here, with their evidence run." />
      : <Table aria-label="Publication history">
        <TableHeader><TableRow><TableHead>Publication</TableHead><TableHead>Destination</TableHead><TableHead>Policy</TableHead><TableHead>Artifact digest</TableHead><TableHead>Evidence run</TableHead><TableHead>Published</TableHead><TableHead>Warnings</TableHead></TableRow></TableHeader>
        <TableBody>{history.data.map(item => <TableRow key={item.id}>
          <TableCell className="font-medium">{item.id}</TableCell>
          <TableCell className="break-all">{item.destination || "-"}</TableCell>
          <TableCell>{item.policy ?? "-"}</TableCell>
          <TableCell><CopyDigest value={item.artifactSha256} /></TableCell>
          <TableCell>{item.runId ? <Link className="underline-offset-4 hover:underline" to={`/review/evidence/${encodeURIComponent(item.runId)}`}>{item.runId}</Link> : "-"}</TableCell>
          <TableCell>{when(item.publishedAt)}</TableCell>
          <TableCell>{item.warnings.length ? item.warnings.join("; ") : "-"}</TableCell>
        </TableRow>)}</TableBody>
      </Table>}
  </section>;
}
