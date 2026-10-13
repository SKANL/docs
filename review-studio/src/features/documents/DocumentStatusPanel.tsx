import type { DocumentRecord } from "@/api/models";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

type Props = { document: DocumentRecord | null; status: Record<string, unknown> | null; loading: boolean; error?: string; onRetry?(): void };

const panel = "grid items-center gap-4 rounded-lg bg-muted p-4 sm:grid-cols-[minmax(0,1fr)_auto]";

export function DocumentStatusPanel({ document, status, loading, error, onRetry }: Props) {
  if (loading) return <section className={panel} aria-label="Document status" aria-busy="true"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-4 w-1/4" /></section>;
  if (!document) return <section className={panel} aria-label="Document status"><p className="text-sm text-muted-foreground">Select a document to inspect its readiness, or create one to get started.</p></section>;
  const blockers = Array.isArray(status?.publication_blockers) ? status.publication_blockers : [];
  const ready = status?.succeeded === true;
  return <section className={panel} aria-label="Document status">
    <div className="min-w-0">
      <p className="text-xs font-semibold tracking-wider text-primary uppercase">Current document</p>
      <h2 className="text-xl font-semibold">{document.title || document.id}</h2>
      <p className="mt-1 text-sm break-words text-muted-foreground">{document.id}{document.template ? ` · ${document.template}` : ""}</p>
    </div>
    <div className="grid gap-1 sm:text-right">
      <span className="text-xs font-medium text-muted-foreground">Service status</span>
      {status ? <Badge variant="outline" className={ready ? "border-success/40 text-success" : "border-warning/50 text-warning"}>{ready ? "Ready" : "Needs attention"}</Badge> : <strong>Status unavailable</strong>}
    </div>
    {error && <div role="alert" className="sm:col-span-2"><p className="text-sm text-destructive">{error}</p>{onRetry && <Button type="button" variant="outline" size="sm" className="mt-2" onClick={onRetry}>Retry document status</Button>}</div>}
    {blockers.length > 0 && <div className="grid gap-1 sm:col-span-2"><span className="text-xs font-medium text-muted-foreground">Reported blockers</span><ul className="list-disc pl-5 text-sm text-destructive">{blockers.map((blocker, index) => <li key={`${String(blocker)}-${index}`}>{typeof blocker === "string" ? blocker : JSON.stringify(blocker)}</li>)}</ul></div>}
  </section>;
}
