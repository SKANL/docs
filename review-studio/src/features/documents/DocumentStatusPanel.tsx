import type { DocumentRecord } from "@/api/models";
import { Badge } from "@/components/ui/badge";
import { ErrorState } from "@/components/shared/ErrorState";
import { useT } from "@/lib/i18n";
import { Skeleton } from "@/components/ui/skeleton";

type Props = { document: DocumentRecord | null; status: Record<string, unknown> | null; loading: boolean; error?: unknown; onRetry?(): void };

const panel = "grid items-center gap-4 rounded-lg bg-muted p-4 sm:grid-cols-[minmax(0,1fr)_auto]";

export function DocumentStatusPanel({ document, status, loading, error, onRetry }: Props) {
  const { t } = useT();
  if (loading) return <section className={panel} aria-label={t("doc.statusLabel")} aria-busy="true"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-4 w-1/4" /></section>;
  if (!document) return <section className={panel} aria-label={t("doc.statusLabel")}><p className="text-sm text-muted-foreground">{t("doc.statusPrompt")}</p></section>;
  const blockers = Array.isArray(status?.publication_blockers) ? status.publication_blockers : [];
  const ready = status?.succeeded === true;
  return <section className={panel} aria-label={t("doc.statusLabel")}>
    <div className="min-w-0">
      <p className="text-xs font-semibold tracking-wider text-primary uppercase">{t("doc.currentDocument")}</p>
      <h2 className="text-xl font-semibold">{document.title || document.id}</h2>
      <p className="mt-1 text-sm break-words text-muted-foreground">{document.id}{document.template ? ` · ${document.template}` : ""}</p>
    </div>
    <div className="grid gap-1 sm:text-right">
      <span className="text-xs font-medium text-muted-foreground">{t("doc.serviceStatus")}</span>
      {status ? <Badge variant="outline" className={ready ? "border-success/40 text-success" : "border-warning/50 text-warning"}>{ready ? t("doc.ready") : t("doc.needsAttention")}</Badge> : <strong>{t("doc.statusUnavailable")}</strong>}
    </div>
    {error != null && <div className="sm:col-span-2"><ErrorState title={t("doc.statusFailed")} error={error} onRetry={onRetry} /></div>}
    {blockers.length > 0 && <div className="grid gap-1 sm:col-span-2"><span className="text-xs font-medium text-muted-foreground">{t("doc.blockers")}</span><ul className="list-disc pl-5 text-sm text-destructive">{blockers.map((blocker, index) => <li key={`${String(blocker)}-${index}`}>{typeof blocker === "string" ? blocker : JSON.stringify(blocker)}</li>)}</ul></div>}
  </section>;
}
