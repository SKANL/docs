import { useIsMutating, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { formatApiError } from "@/api/errors";
import type { Workspace } from "@/api/models";
import { useApi } from "@/app/providers";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { ErrorState } from "@/components/shared/ErrorState";
import { Button } from "@/components/ui/button";
import { useAction } from "@/lib/actions";
import { WorkspaceFormDialog } from "./WorkspaceFormDialog";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";
import { kickerClass, refreshWorkspaceData, sectionClass, workspaceKeys } from "./data";

type Props = { workspaces: Workspace[]; loading: boolean; onNotice(message: string): void };

/** Which workspace is selected, and the operations on it: create, rename, delete. */
export function WorkspaceSection({ workspaces, loading, onNotice }: Props) {
  const api = useApi();
  const busy = useIsMutating() > 0;
  const selected = workspaces[0] ?? null; // the server lists the selected workspace first
  const status = useQuery({ queryKey: workspaceKeys.status(selected?.id ?? ""), queryFn: () => api.getWorkspaceStatus!(selected!.id), enabled: !!selected && !!api.getWorkspaceStatus });
  const [form, setForm] = useState<"create" | "rename" | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const common = { notify: onNotice, invalidate: refreshWorkspaceData };

  const select = useAction((id: string) => api.selectWorkspace!(id), { ...common });
  const save = useAction(
    (input: { mode: "create" | "rename"; name: string }) => input.mode === "create" ? api.createWorkspace!({ name: input.name }) : api.renameWorkspace!(selected!.id, input.name),
    { ...common, success: (workspace, input) => input.mode === "create" ? `Workspace ${workspace.name} created.` : "Workspace name updated.", onDone: () => setForm(null) },
  );
  const remove = useAction(async (id: string) => {
    await api.deleteWorkspace!(id);
    const next = workspaces.find(item => item.id !== id);
    if (next && api.selectWorkspace) await api.selectWorkspace(next.id);
  }, { ...common, success: () => "Workspace deleted.", onDone: () => setDeleteOpen(false) });
  const dismissable = (action: { isError: boolean; reset(): void }, close: () => void) => () => { close(); if (action.isError) action.reset(); };

  return <section className={sectionClass} aria-labelledby="workspace-heading">
    <div className="flex items-center justify-between gap-4"><div><p className={kickerClass}>Operating context</p><h2 id="workspace-heading" className="text-xl font-semibold">Workspace</h2></div>{selected && <span className="text-sm text-muted-foreground">{status.data?.active ? "Active on service" : "Selected on this device"}</span>}</div>
    {select.isError && <ErrorState error={select.error} />}
    {workspaces.length > 0 ? <>
      <WorkspaceSwitcher workspaces={workspaces} selectedId={selected?.id ?? ""} busy={busy} canCreate={Boolean(api.createWorkspace)} canSelect={Boolean(api.selectWorkspace)} onSelect={id => { if (id !== selected?.id) select.mutate(id); }} onCreate={() => setForm("create")} />
      {selected && <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"><div className="grid min-w-0 gap-1"><span className="text-xs font-medium text-muted-foreground">Storage location</span><code className="text-sm break-all text-muted-foreground">{selected.root}</code></div><div className="flex flex-wrap gap-1.5 sm:justify-end">
        <Button type="button" variant="ghost" onClick={() => setForm("rename")} disabled={busy || !api.renameWorkspace}>Rename workspace</Button>
        <Button type="button" variant="destructive" onClick={() => setDeleteOpen(true)} disabled={busy || !api.deleteWorkspace}>Delete workspace</Button>
      </div></div>}
    </> : !loading && <div className="max-w-2xl rounded-lg bg-muted p-5"><h3 className="font-semibold">No workspace yet</h3><p className="mt-1 mb-3 text-sm leading-relaxed text-muted-foreground">Create one to initialize its storage and start a document. In desktop mode, the local service stores managed workspaces under the app-data workspace.</p><Button type="button" onClick={() => setForm("create")} disabled={!api.createWorkspace}>Create workspace</Button></div>}

    <WorkspaceFormDialog mode={form ?? "create"} workspace={selected ?? undefined} open={form !== null} pending={save.isPending} error={save.isError ? formatApiError(save.error) : undefined} onOpenChange={open => { if (!open) dismissable(save, () => setForm(null))(); }} onSubmit={name => save.mutate({ mode: form ?? "create", name })} />
    <ConfirmActionDialog open={deleteOpen} onOpenChange={open => { if (!open) dismissable(remove, () => setDeleteOpen(false))(); }} title="Delete workspace" description="This removes the workspace from the registry. Its files are not deleted. You cannot undo this registry change." confirmLabel="Delete workspace" pending={remove.isPending} error={remove.isError ? formatApiError(remove.error) : undefined} onConfirm={() => remove.mutate(selected!.id)} />
  </section>;
}
