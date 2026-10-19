import { useState } from "react";
import { ApiError } from "@/api/errors";
import type { BaselinePromotion } from "@/api/domains/review";
import { useApi } from "@/app/providers";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ActionError, useAction } from "@/lib/actions";
import { Digest } from "@/components/shared/Facts";
import { ErrorState } from "@/components/shared/ErrorState";
import { useT } from "@/lib/i18n";
import { reviewKeys } from "./data";

/**
 * Promote a run's rendered pages to a baseline. Replacing an existing baseline is a separate,
 * explicit second confirmation: the first attempt never sends `update`.
 */
export function BaselinePromotionDialog({ workspaceId, runId, onClose }: { workspaceId: string | null; runId: string; onClose(): void }) {
  const { t } = useT();
  const api = useApi();
  const [name, setName] = useState(runId);
  const [done, setDone] = useState<BaselinePromotion | null>(null);
  const promote = useAction((update: boolean) => api.promoteBaseline!({ runId, name: name.trim() || undefined, update }), {
    success: result => t("rv.promo.done", { name: result.name }),
    invalidate: [reviewKeys.baselines(workspaceId)],
    onDone: setDone,
  });
  const exists = promote.error instanceof ApiError && promote.error.code === "baseline_exists";
  const busy = promote.isPending;
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{t("rv.promo.title")}</DialogTitle>
        <DialogDescription>{t("rv.promo.body", { id: runId })}</DialogDescription>
      </DialogHeader>
      {done ? <div className="grid gap-2 text-sm" role="status">
        <p>{done.replaced ? t("rv.promo.replaced") : t("rv.promo.saved")} <b>{done.destination}</b>.</p>
        <ul className="grid gap-1">{done.pages.map(page => <li key={page.name} className="flex flex-wrap gap-2"><span>{page.name}</span><Digest value={page.sha256} /></li>)}</ul>
      </div> : <div className="grid gap-4">
        <div className="grid gap-1"><Label htmlFor="baseline-name">{t("rv.promo.name")}</Label>
          <Input id="baseline-name" value={name} disabled={busy} onChange={event => { setName(event.target.value); promote.reset(); }} /></div>
        {exists && <div className="grid gap-2 rounded-md border border-destructive/40 p-3 text-sm" role="alert">
          <ErrorState error={promote.error} />
          <p>{t("rv.promo.replaceWarning")}</p>
          <Button type="button" variant="destructive" className="w-fit" disabled={busy} onClick={() => promote.mutate(true)}>{t("rv.promo.replace")}</Button>
        </div>}
        {!exists && <ActionError action={promote} what={t("act.promoteBaseline")} />}
      </div>}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>{done ? t("common.close") : t("common.cancel")}</Button>
        {!done && <Button type="button" disabled={busy || exists} onClick={() => promote.mutate(false)}>{t("rv.promo.promote")}</Button>}
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
