import { useState } from "react";
import { ApiError } from "@/api/client";
import type { BaselinePromotion } from "@/api/domains/review";
import { useApi } from "@/app/providers";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ActionError, errorText, useAction } from "@/features/authoring/data";
import { Digest, reviewKeys } from "./data";

/**
 * Promote a run's rendered pages to a baseline. Replacing an existing baseline is a separate,
 * explicit second confirmation: the first attempt never sends `update`.
 */
export function BaselinePromotionDialog({ workspaceId, runId, onClose }: { workspaceId: string | null; runId: string; onClose(): void }) {
  const api = useApi();
  const [name, setName] = useState(runId);
  const [done, setDone] = useState<BaselinePromotion | null>(null);
  const promote = useAction((update: boolean) => api.promoteBaseline!({ runId, name: name.trim() || undefined, update }), {
    success: result => `Baseline ${result.name} saved.`,
    invalidate: [reviewKeys.baselines(workspaceId)],
    onDone: setDone,
  });
  const exists = promote.error instanceof ApiError && promote.error.code === "baseline_exists";
  const busy = promote.isPending;
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Promote to baseline</DialogTitle>
        <DialogDescription>Run {runId}&apos;s rendered pages become the approved reference that later runs are compared against.</DialogDescription>
      </DialogHeader>
      {done ? <div className="grid gap-2 text-sm" role="status">
        <p>{done.replaced ? "Replaced the existing baseline at" : "Saved a new baseline at"} <b>{done.destination}</b>.</p>
        <ul className="grid gap-1">{done.pages.map(page => <li key={page.name} className="flex flex-wrap gap-2"><span>{page.name}</span><Digest value={page.sha256} /></li>)}</ul>
      </div> : <div className="grid gap-4">
        <div className="grid gap-1"><Label htmlFor="baseline-name">Baseline name</Label>
          <Input id="baseline-name" value={name} disabled={busy} onChange={event => { setName(event.target.value); promote.reset(); }} /></div>
        {exists && <div className="grid gap-2 rounded-md border border-destructive/40 p-3 text-sm" role="alert">
          <p>{errorText(promote.error, "baseline")}</p>
          <p>Replacing overwrites the approved pages of this baseline. Confirm only if the new render is the correct reference.</p>
          <Button type="button" variant="destructive" className="w-fit" disabled={busy} onClick={() => promote.mutate(true)}>Replace existing baseline</Button>
        </div>}
        {!exists && <ActionError action={promote} what="promote the baseline" />}
      </div>}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>{done ? "Close" : "Cancel"}</Button>
        {!done && <Button type="button" disabled={busy || exists} onClick={() => promote.mutate(false)}>Promote baseline</Button>}
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
