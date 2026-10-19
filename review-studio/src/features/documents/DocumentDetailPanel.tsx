import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/app/providers";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { StructureView } from "@/components/shared/StructureView";
import { useCapability } from "@/lib/capability-registry";
import { useT } from "@/lib/i18n";

/** `doc show` (the record) and `doc status` (the resumable summary) for one document, as readable labels. */
export function DocumentDetailPanel({ documentId }: { documentId: string }) {
  const api = useApi();
  const can = useCapability();
  const { t } = useT();
  const showable = can("doc.show") && !!api.getDocument;
  const summarizable = can("doc.status") && !!api.getDocumentSummary;
  const record = useQuery({ queryKey: ["document-detail", documentId], queryFn: () => api.getDocument!(documentId), enabled: showable });
  const summary = useQuery({ queryKey: ["document-summary", documentId], queryFn: () => api.getDocumentSummary!(documentId), enabled: summarizable });
  if (!showable && !summarizable) return null;
  return <section aria-label={t("doc.details")} className="grid gap-4 rounded-lg border bg-card p-4">
    <h3 className="text-lg font-semibold">{t("doc.details")}</h3>
    {showable && <QueryBoundary query={record} skeleton="h-12 w-full">{data => <StructureView value={data} label={t("doc.record")} />}</QueryBoundary>}
    {summarizable && <div className="grid gap-2"><h4 className="text-sm font-semibold">{t("doc.stands")}</h4>
      <QueryBoundary query={summary} skeleton="h-12 w-full">{data => <StructureView value={data.summary} label={t("doc.summary")} />}</QueryBoundary></div>}
  </section>;
}
