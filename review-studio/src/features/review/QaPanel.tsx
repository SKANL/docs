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
import { ActionError, useAction } from "@/lib/actions";
import { Unavailable } from "@/components/shared/Unavailable";
import { useActiveContext } from "@/app/active-context";
import { useCapability } from "@/lib/capability-registry";
import { useT } from "@/lib/i18n";

function QaResult({ result }: { result: QaDocxResult }) {
  const { t } = useT();
  return <section aria-label={t("rv.qa.resultLabel")} className="grid gap-2 rounded-lg border bg-card p-4">
    <div className="flex items-center gap-2"><h3 className="text-lg font-semibold">{t("rv.qa.result")}</h3>
      <Badge variant={result.degraded ? "secondary" : result.passed ? "default" : "destructive"}>{result.degraded ? t("rv.qa.degraded") : result.passed ? t("rv.qa.passed") : t("rv.qa.failed")}</Badge>
      {result.strict && <Badge variant="outline">{t("rv.qa.strictBadge")}</Badge>}</div>
    {result.degraded && <Alert variant="destructive" role="alert"><AlertTitle>{t("rv.qa.degradedTitle")}</AlertTitle><AlertDescription>{t("rv.qa.degradedBody", { reason: result.degraded_reason ?? t("rv.qa.noReason") })}</AlertDescription></Alert>}
    {result.message && <p className="text-sm">{result.message}</p>}
    <p className="text-sm text-muted-foreground">{result.report ? t("rv.qa.checkedReport", { docx: result.docx, report: result.report }) : t("rv.qa.checked", { docx: result.docx })}</p>
  </section>;
}

export function QaPanel() {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const active = useActiveContext();
  const [strict, setStrict] = useState(false);
  const [result, setResult] = useState<QaDocxResult | null>(null);
  const [confirming, setConfirming] = useState(false);
  const documentId = active.data?.documentId ?? "";
  const qa = useAction(() => api.runQaDocx!(documentId, { strict }), { success: () => t("rv.qa.finished"), onDone: setResult });
  const corrections = useAction(() => api.applyCorrections!(documentId), {
    success: ({ applied }) => t(applied === 1 ? "rv.qa.applied.one" : "rv.qa.applied.other", { count: applied }), onDone: () => setConfirming(false),
  });
  if (active.isPending) return null;
  if (!documentId) return <EmptyState title={t("rv.qa.selectDoc.title")} description={t("rv.qa.selectDoc.body")}><Button asChild><Link to="/configure/workspaces">{t("rv.openWorkspaces")}</Link></Button></EmptyState>;
  const canQa = can("qa-docx") && !!api.runQaDocx;
  const canFix = can("apply-corrections") && !!api.applyCorrections;
  return <div className="grid gap-6">
    <p className="text-sm text-muted-foreground">{t("rv.qa.document")} <b>{documentId}</b></p>
    {!canQa && <Unavailable>{t("rv.qa.unavailable")}</Unavailable>}
    {canQa && <section aria-label={t("rv.qa.checkLabel")} className="grid gap-3 rounded-lg border bg-card p-4">
      <h3 className="text-lg font-semibold">{t("rv.qa.checkLabel")}</h3>
      <p className="text-sm text-muted-foreground">{t("rv.qa.checkBody")}</p>
      <div className="flex items-center gap-2"><Switch id="qa-strict" checked={strict} onCheckedChange={setStrict} /><Label htmlFor="qa-strict">{t("rv.qa.strict")}</Label></div>
      <Button type="button" className="w-fit" disabled={qa.isPending} onClick={() => qa.mutate(undefined)}>{t("rv.qa.run")}</Button>
      <ActionError action={qa} what={t("act.runQa")} />
    </section>}
    {result && <QaResult result={result} />}
    {canFix && <section aria-label={t("rv.qa.corrections")} className="grid gap-3 rounded-lg border bg-card p-4">
      <h3 className="text-lg font-semibold">{t("rv.qa.corrections")}</h3>
      <p className="text-sm text-muted-foreground">{t("rv.qa.correctionsBody")}</p>
      <Button type="button" variant="outline" className="w-fit" onClick={() => setConfirming(true)}>{t("rv.qa.apply")}</Button>
    </section>}
    <ConfirmActionDialog open={confirming} onOpenChange={setConfirming} title={t("rv.qa.applyTitle")} description={t("rv.qa.applyBody", { id: documentId })}
      confirmLabel={t("rv.qa.apply")} pending={corrections.isPending} error={corrections.error} onConfirm={() => corrections.mutate(undefined)} />
  </div>;
}
