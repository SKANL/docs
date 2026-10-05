import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import type { QaDocxResult } from "@/api/domains/review";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { EmptyState } from "@/components/shared/EmptyState";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ActionError, Unavailable, errorText, useAction, useActiveContext, useCapability } from "@/features/authoring/data";

function QaResult({ result }: { result: QaDocxResult }) {
  return <section aria-label="QA result" className="grid gap-2 rounded-lg border bg-card p-4">
    <div className="flex items-center gap-2"><h3 className="text-lg font-semibold">Result</h3>
      <Badge variant={result.degraded ? "secondary" : result.passed ? "default" : "destructive"}>{result.degraded ? "degraded" : result.passed ? "passed" : "failed"}</Badge>
      {result.strict && <Badge variant="outline">strict</Badge>}</div>
    {result.degraded && <Alert variant="destructive" role="alert"><AlertTitle>Degraded</AlertTitle><AlertDescription>The visual check did not fully run: {result.degraded_reason ?? "no reason was reported"}.</AlertDescription></Alert>}
    {result.message && <p className="text-sm">{result.message}</p>}
    <p className="text-sm text-muted-foreground">Checked {result.docx}{result.report ? `; report at ${result.report}` : ""}.</p>
  </section>;
}

export function QaPanel() {
  const api = useApi();
  const can = useCapability();
  const active = useActiveContext();
  const [strict, setStrict] = useState(false);
  const [result, setResult] = useState<QaDocxResult | null>(null);
  const [confirming, setConfirming] = useState(false);
  const documentId = active.data?.documentId ?? "";
  const qa = useAction(() => api.runQaDocx!(documentId, { strict }), { success: () => "DOCX QA finished.", onDone: setResult });
  const corrections = useAction(() => api.applyCorrections!(documentId), {
    success: ({ applied }) => `Applied ${applied} correction${applied === 1 ? "" : "s"}.`, onDone: () => setConfirming(false),
  });
  if (active.isPending) return null;
  if (!documentId) return <EmptyState title="Select a document first" description="Quality checks run on the current document."><Button asChild><Link to="/configure/workspaces">Open workspaces and documents</Link></Button></EmptyState>;
  const canQa = can("qa-docx") && !!api.runQaDocx;
  const canFix = can("apply-corrections") && !!api.applyCorrections;
  return <div className="grid gap-6">
    <p className="text-sm text-muted-foreground">Document <b>{documentId}</b></p>
    {!canQa && <Unavailable>Rendered DOCX QA is not available on this server.</Unavailable>}
    {canQa && <section aria-label="DOCX quality check" className="grid gap-3 rounded-lg border bg-card p-4">
      <h3 className="text-lg font-semibold">DOCX quality check</h3>
      <p className="text-sm text-muted-foreground">Renders the built DOCX and checks the pages. Without a render toolchain the result is reported as degraded, with the reason.</p>
      <div className="flex items-center gap-2"><Switch id="qa-strict" checked={strict} onCheckedChange={setStrict} /><Label htmlFor="qa-strict">Strict mode</Label></div>
      <Button type="button" className="w-fit" disabled={qa.isPending} onClick={() => qa.mutate(undefined)}>Run DOCX QA</Button>
      <ActionError action={qa} what="run DOCX QA" />
    </section>}
    {result && <QaResult result={result} />}
    {canFix && <section aria-label="Corrections" className="grid gap-3 rounded-lg border bg-card p-4">
      <h3 className="text-lg font-semibold">Corrections</h3>
      <p className="text-sm text-muted-foreground">Applies the pending section corrections to the document sources.</p>
      <Button type="button" variant="outline" className="w-fit" onClick={() => setConfirming(true)}>Apply corrections</Button>
    </section>}
    <ConfirmActionDialog open={confirming} onOpenChange={setConfirming} title="Apply pending corrections?" description={`This edits the section files of ${documentId}. Review them in Authoring afterwards.`}
      confirmLabel="Apply corrections" pending={corrections.isPending} error={corrections.isError ? errorText(corrections.error, "corrections") : undefined} onConfirm={() => corrections.mutate(undefined)} />
  </div>;
}
