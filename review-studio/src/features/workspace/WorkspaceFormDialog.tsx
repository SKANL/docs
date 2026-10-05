import { useEffect, useState, type FormEvent } from "react";
import type { Workspace } from "../../api/models";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";

type Props = { mode: "create" | "rename"; workspace?: Workspace; open: boolean; pending: boolean; error?: string; onOpenChange(open: boolean): void; onSubmit(name: string): void };

export function WorkspaceFormDialog({ mode, workspace, open, pending, error, onOpenChange, onSubmit }: Props) {
  const [name, setName] = useState("");
  useEffect(() => { if (open) setName(mode === "rename" ? workspace?.name ?? "" : ""); }, [mode, open, workspace?.id, workspace?.name]);
  const title = mode === "create" ? "Create workspace" : "Rename workspace";
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(name.trim());
  }
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent aria-describedby="workspace-form-description">
      <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription id="workspace-form-description">Workspaces keep documents and their source material in separate locations.</DialogDescription></DialogHeader>
      {pending && <p className="ws-muted" role="status">This request cannot be cancelled after it is sent. You may close this dialog; the action will finish and controls stay unavailable until then.</p>}
      <form onSubmit={submit}>
        <label className="field-label" htmlFor="workspace-name">Workspace name</label>
        <Input id="workspace-name" name="name" autoComplete="off" required maxLength={64} value={name} onChange={event => setName(event.target.value)} />
        {error && <p className="inline-error" role="alert">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Close</Button>
          <Button type="submit" disabled={pending || !name.trim()}>{pending ? "Saving…" : title}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
