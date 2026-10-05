import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/app/providers";
import { ErrorState } from "@/components/shared/ErrorState";
import { StructureView } from "@/components/shared/StructureView";
import { Skeleton } from "@/components/ui/skeleton";
import { errorText, useCapability } from "@/features/authoring/data";

/** `doc show` (the record) and `doc status` (the resumable summary) for one document, as readable labels. */
export function DocumentDetailPanel({ documentId }: { documentId: string }) {
  const api = useApi();
  const can = useCapability();
  const showable = can("doc.show") && !!api.getDocument;
  const summarizable = can("doc.status") && !!api.getDocumentSummary;
  const record = useQuery({ queryKey: ["document-detail", documentId], queryFn: () => api.getDocument!(documentId), enabled: showable });
  const summary = useQuery({ queryKey: ["document-summary", documentId], queryFn: () => api.getDocumentSummary!(documentId), enabled: summarizable });
  if (!showable && !summarizable) return null;
  return <section aria-label="Document details" className="grid gap-4 rounded-lg border bg-card p-4">
    <h3 className="text-lg font-semibold">Document details</h3>
    {showable && (record.isPending ? <Skeleton className="h-12 w-full" /> : record.isError ? <ErrorState message={errorText(record.error, "document")} onRetry={() => void record.refetch()} /> : <StructureView value={record.data} label="Document record" />)}
    {summarizable && <div className="grid gap-2"><h4 className="text-sm font-semibold">Where this document stands</h4>
      {summary.isPending ? <Skeleton className="h-12 w-full" /> : summary.isError ? <ErrorState message={errorText(summary.error, "summary")} onRetry={() => void summary.refetch()} /> : <StructureView value={summary.data.summary} label="Document summary" />}</div>}
  </section>;
}
