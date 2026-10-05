import type { DocumentRecord } from "../../api/models";
import { Button } from "../../components/ui/button";

type Props = { document: DocumentRecord | null; status: Record<string, unknown> | null; loading: boolean; error?: string; onRetry?(): void };

export function DocumentStatusPanel({ document, status, loading, error, onRetry }: Props) {
  if (loading) return <section className="ws-status-panel" aria-label="Document status" aria-busy="true"><span className="ws-skeleton" /><span className="ws-skeleton ws-skeleton-short" /></section>;
  if (!document) return <section className="ws-status-panel" aria-label="Document status"><p className="ws-muted">Select a document to inspect its readiness, or create one to get started.</p></section>;
  const blockers = Array.isArray(status?.publication_blockers) ? status.publication_blockers : [];
  return <section className="ws-status-panel" aria-label="Document status">
    <div><p className="ws-kicker">Current document</p><h2>{document.title || document.id}</h2><p className="ws-muted">{document.id}{document.template ? ` · ${document.template}` : ""}</p></div>
    <div className="ws-status-detail"><span className="ws-status-label">Service status</span><strong>{status ? (status.succeeded === true ? "Ready" : "Needs attention") : "Status unavailable"}</strong></div>
    {error && <div role="alert"><p className="inline-error">{error}</p>{onRetry && <Button type="button" variant="outline" onClick={onRetry}>Retry document status</Button>}</div>}
    {blockers.length > 0 && <div className="ws-blockers"><span className="ws-status-label">Reported blockers</span><ul>{blockers.map((blocker, index) => <li key={`${String(blocker)}-${index}`}>{typeof blocker === "string" ? blocker : JSON.stringify(blocker)}</li>)}</ul></div>}
  </section>;
}
