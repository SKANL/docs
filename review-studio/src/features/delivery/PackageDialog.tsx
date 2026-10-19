import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useApi } from "@/app/providers";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ActionError, useAction } from "@/lib/actions";
import { useCapability } from "@/lib/capability-registry";
import { statusKey, useT } from "@/lib/i18n";
import { Facts } from "@/components/shared/Facts";
import type { PackageInput } from "@/api/domains/delivery";
import { deliveryKeys } from "./data";

const CURRENT = "current";
type Props = { open: boolean; workspaceId: string | null; documentId: string; onOpenChange(open: boolean): void };

/** Cuts the document's build output into an archive. The result (path and digest) is whatever the server returned. */
export function PackageDialog({ open, workspaceId, documentId, onOpenChange }: Props) {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const [name, setName] = useState("");
  const [runId, setRunId] = useState(CURRENT);
  const runs = useQuery({
    queryKey: deliveryKeys.runs(workspaceId, documentId),
    queryFn: () => api.listRunPage!({ documentId, limit: 20 }),
    enabled: open && !!api.listRunPage && can("run.list"),
  });
  const pack = useAction((input: PackageInput) => api.packageDocument!(documentId, input), { success: result => t("dl.pkg.toast", { destination: result.destination }) });
  useEffect(() => { if (open) { setName(""); setRunId(CURRENT); pack.reset(); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const request: PackageInput = { ...(name.trim() ? { name: name.trim() } : {}), ...(runId === CURRENT ? {} : { runId }) };
  const submit = (event: FormEvent) => { event.preventDefault(); pack.mutate(request); };
  const result = pack.data;

  return <Dialog open={open} onOpenChange={next => { if (!pack.isPending) onOpenChange(next); }}>
    <DialogContent showCloseButton={false} aria-describedby="package-description">
      <DialogHeader><DialogTitle>{t("dl.pkg.title")}</DialogTitle>
        <DialogDescription id="package-description">{t("dl.pkg.body")}</DialogDescription></DialogHeader>
      <form onSubmit={submit} className="grid gap-4">
        <div className="grid gap-2"><Label htmlFor="package-name">{t("dl.pkg.name")}</Label>
          <Input id="package-name" autoComplete="off" value={name} onChange={event => setName(event.target.value)} /></div>
        {(runs.data?.items.length ?? 0) > 0 && <div className="grid gap-2"><Label htmlFor="package-run">{t("dl.pkg.run")}</Label>
          <Select value={runId} onValueChange={setRunId}>
            <SelectTrigger id="package-run" aria-label={t("dl.pkg.run")} className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={CURRENT}>{t("dl.pkg.current")}</SelectItem>
              {runs.data!.items.map(item => <SelectItem key={item.id} value={item.id}>{item.id} ({statusKey("run.status", item.status) ? t(statusKey("run.status", item.status)!) : item.status})</SelectItem>)}
            </SelectContent>
          </Select></div>}
        <ActionError action={pack} what={t("act.package")} />
        {result && <section role="status" aria-label={t("dl.pkg.resultLabel")} className="grid gap-2 rounded-md border p-3">
          <p className="font-medium">{t("dl.pkg.created")}</p>
          <Facts rows={[[t("dl.pkg.archive"), result.destination], [t("dl.pkg.source"), result.source], [t("dl.pkg.size"), t("src.bytes", { size: result.size_bytes })], [t("dl.pkg.run2"), result.run_id ?? undefined], [t("rv.insp.sha"), <code key="d" className="text-xs break-all">{result.sha256}</code>]]} />
        </section>}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={pack.isPending}>{t("common.close")}</Button>
          <Button type="submit" disabled={pack.isPending}>{pack.isPending ? t("dl.pkg.packaging") : t("dl.pkg.create")}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
