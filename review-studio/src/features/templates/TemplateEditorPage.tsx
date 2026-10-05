import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { ErrorState } from "@/components/shared/ErrorState";
import { StructureView } from "@/components/shared/StructureView";
import { ApiError } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ActionError, Unavailable, errorText, useAction, useActiveContext, useCapability } from "@/features/authoring/data";
import { TemplateValidationPanel } from "./TemplateValidationPanel";

const keys = {
  installed: (ws: string | null) => ["configure", ws, "templates"],
  catalog: (ws: string | null) => ["configure", ws, "template-catalog"],
  shown: (ws: string | null, name: string) => ["configure", ws, "template", name],
};

/** Installed templates, the built-in catalogue, a structural view, install, create, and validation. */
export function TemplateEditorPage() {
  const api = useApi();
  const can = useCapability();
  const workspaceId = useActiveContext().data?.workspaceId ?? null;
  const [shown, setShown] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const listable = can("template.list");

  const installed = useQuery({ queryKey: keys.installed(workspaceId), queryFn: () => api.listTemplates!(), enabled: listable && !!api.listTemplates });
  const catalog = useQuery({ queryKey: keys.catalog(workspaceId), queryFn: () => api.listTemplateCatalog!(), enabled: listable && !!api.listTemplateCatalog });
  const detail = useQuery({ queryKey: keys.shown(workspaceId, shown ?? ""), queryFn: () => api.showTemplate!(shown!), enabled: !!shown && can("template.show") && !!api.showTemplate });

  const refresh = [keys.installed(workspaceId), keys.catalog(workspaceId)];
  const install = useAction((input: { name: string; force: boolean }) => api.installBuiltinTemplate!(input.name, { force: input.force }), {
    success: result => `Installed ${result.name} at ${result.path}.`, invalidate: refresh,
  });
  const create = useAction((name: string) => api.createTemplate!(name), {
    success: result => `Created ${result.name} at ${result.path}.`, invalidate: refresh, onDone: () => setNewName(""),
  });
  const exists = install.error instanceof ApiError && install.error.code === "template_exists" && !install.variables?.force;
  const canCreate = (can("template.create") || can("template.init")) && !!api.createTemplate;

  return <div className="grid gap-8">
    <section aria-label="Installed" className="grid gap-3">
      <h2 className="text-xl font-semibold">Installed templates</h2>
      {!listable || !api.listTemplates ? <Unavailable>Listing templates is not available on this server.</Unavailable>
        : installed.isPending ? <Skeleton className="h-16 w-full" />
        : installed.isError ? <ErrorState message={errorText(installed.error, "templates")} onRetry={() => void installed.refetch()} />
        : installed.data.length === 0 ? <p className="text-sm text-muted-foreground">No templates are installed in this workspace. Install a built-in one or create a new template.</p>
        : <Table aria-label="Installed templates">
          <TableHeader><TableRow><TableHead>Template</TableHead><TableHead>Version</TableHead><TableHead className="w-28"><span className="sr-only">Actions</span></TableHead></TableRow></TableHeader>
          <TableBody>{installed.data.map(item => <TableRow key={item.id}>
            <TableCell className="font-medium">{item.name || item.id}</TableCell><TableCell>{item.version}</TableCell>
            <TableCell>{can("template.show") && api.showTemplate && <Button type="button" variant="ghost" size="sm" aria-label={`Show ${item.id}`} onClick={() => setShown(item.id)}>Show</Button>}</TableCell>
          </TableRow>)}</TableBody>
        </Table>}
      {shown && <section aria-label="Template structure" className="grid gap-2 rounded-lg border bg-card p-4">
        <h3 className="text-lg font-semibold">{shown}</h3>
        {detail.isPending ? <Skeleton className="h-16 w-full" /> : detail.isError ? <ErrorState message={errorText(detail.error, "template")} onRetry={() => void detail.refetch()} />
          : <StructureView value={detail.data.template} />}
      </section>}
    </section>

    <section aria-label="Catalogue" className="grid gap-3">
      <h2 className="text-xl font-semibold">Built-in catalogue</h2>
      {!listable || !api.listTemplateCatalog ? <Unavailable>The built-in catalogue is not available on this server.</Unavailable>
        : catalog.isPending ? <Skeleton className="h-16 w-full" />
        : catalog.isError ? <ErrorState message={errorText(catalog.error, "catalogue")} onRetry={() => void catalog.refetch()} />
        : <Table aria-label="Built-in catalogue">
          <TableHeader><TableRow><TableHead>Template</TableHead><TableHead>State</TableHead><TableHead className="w-32"><span className="sr-only">Actions</span></TableHead></TableRow></TableHeader>
          <TableBody>{catalog.data.map(item => <TableRow key={item.name}>
            <TableCell className="font-medium">{item.name}</TableCell>
            <TableCell><Badge variant={item.installed ? "secondary" : "outline"}>{item.installed ? "Installed" : "Not installed"}</Badge></TableCell>
            <TableCell>{can("template.use") && api.installBuiltinTemplate && <Button type="button" variant="outline" size="sm" aria-label={`Install ${item.name}`} disabled={install.isPending} onClick={() => install.mutate({ name: item.name, force: false })}>{item.installed ? "Reinstall" : "Install"}</Button>}</TableCell>
          </TableRow>)}</TableBody>
        </Table>}
      {!exists && <ActionError action={install} what="install the template" />}
      <ConfirmActionDialog open={exists} title={`Replace ${install.variables?.name ?? "template"}?`}
        description="A template with this name is already installed. Replacing it overwrites that file with the built-in version."
        confirmLabel="Replace template" pending={install.isPending}
        onOpenChange={open => { if (!open) install.reset(); }} onConfirm={() => install.variables && install.mutate({ name: install.variables.name, force: true })} />
    </section>

    {canCreate && <section aria-label="Create" className="grid gap-3">
      <h2 className="text-xl font-semibold">Create a template</h2>
      <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); if (newName.trim()) create.mutate(newName.trim()); }}>
        <div className="grid gap-1"><Label htmlFor="new-template">New template name</Label><Input id="new-template" autoComplete="off" value={newName} onChange={event => setNewName(event.target.value)} /></div>
        <Button type="submit" disabled={!newName.trim() || create.isPending}>Create template</Button>
      </form>
      <ActionError action={create} what="create the template" />
    </section>}

    {can("template.validate") && api.validateTemplate && <TemplateValidationPanel initialName={shown ?? ""} />}
  </div>;
}
