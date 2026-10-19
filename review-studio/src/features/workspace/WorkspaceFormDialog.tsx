import { useEffect, useState, type FormEvent } from "react";
import type { Workspace } from "@/api/models";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ErrorState } from "@/components/shared/ErrorState";
import { Label } from "@/components/ui/label";
import { useT } from "@/lib/i18n";

type Props = { mode: "create" | "rename"; workspace?: Workspace; open: boolean; pending: boolean; error?: unknown; onOpenChange(open: boolean): void; onSubmit(name: string): void };

export function WorkspaceFormDialog({ mode, workspace, open, pending, error, onOpenChange, onSubmit }: Props) {
  const { t } = useT();
  const [name, setName] = useState("");
  useEffect(() => { if (open) setName(mode === "rename" ? workspace?.name ?? "" : ""); }, [mode, open, workspace?.id, workspace?.name]);
  const title = mode === "create" ? t("ws.create") : t("ws.rename");
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(name.trim());
  }
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent showCloseButton={false} aria-describedby="workspace-form-description">
      <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription id="workspace-form-description">{t("ws.dialogBody")}</DialogDescription></DialogHeader>
      {pending && <p className="text-sm text-muted-foreground" role="status">{t("common.pendingNote")}</p>}
      <form onSubmit={submit} className="grid gap-4">
        <div className="grid gap-2"><Label htmlFor="workspace-name">{t("ws.name")}</Label><Input id="workspace-name" name="name" autoComplete="off" required maxLength={64} value={name} onChange={event => setName(event.target.value)} /></div>
        {error != null && <ErrorState error={error} />}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>{t("common.close")}</Button>
          <Button type="submit" disabled={pending || !name.trim()}>{pending ? t("common.saving") : title}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
