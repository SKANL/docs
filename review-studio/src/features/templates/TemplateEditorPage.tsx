import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { StructureView } from "@/components/shared/StructureView";
import { ApiError } from "@/api/errors";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ActionError, useAction } from "@/lib/actions";
import { Unavailable } from "@/components/shared/Unavailable";
import { useActiveContext } from "@/app/active-context";
import { useCapability } from "@/lib/capability-registry";
import { useT } from "@/lib/i18n";
import { TemplateValidationPanel } from "./TemplateValidationPanel";

const keys = {
  installed: (ws: string | null) => ["configure", ws, "templates"],
  catalog: (ws: string | null) => ["configure", ws, "template-catalog"],
  shown: (ws: string | null, name: string) => ["configure", ws, "template", name],
};

/** Installed templates, the built-in catalogue, a structural view, install, create, and validation. */
export function TemplateEditorPage() {
  const { t } = useT();
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
    success: result => t("tp.installedToast", { name: result.name, path: result.path }), invalidate: refresh,
  });
  const create = useAction((name: string) => api.createTemplate!(name), {
    success: result => t("tp.createdToast", { name: result.name, path: result.path }), invalidate: refresh, onDone: () => setNewName(""),
  });
  const exists = install.error instanceof ApiError && install.error.code === "template_exists" && !install.variables?.force;
  const canCreate = (can("template.create") || can("template.init")) && !!api.createTemplate;

  return <div className="grid gap-8">
    <section aria-label={t("tp.installed")} className="grid gap-3">
      <h2 className="text-xl font-semibold">{t("tp.installedHeading")}</h2>
      {!listable || !api.listTemplates ? <Unavailable>{t("tp.listUnavailable")}</Unavailable>
        : <QueryBoundary query={installed} skeleton="h-16 w-full">{templates => templates.length === 0 ? <p className="text-sm text-muted-foreground">{t("tp.noneInstalled")}</p>
        : <Table aria-label={t("tp.installedHeading")}>
          <TableHeader><TableRow><TableHead>{t("tp.template")}</TableHead><TableHead>{t("tp.version")}</TableHead><TableHead className="w-28"><span className="sr-only">{t("tp.actions")}</span></TableHead></TableRow></TableHeader>
          <TableBody>{templates.map(item => <TableRow key={item.id}>
            <TableCell className="font-medium">{item.name || item.id}</TableCell><TableCell>{item.version}</TableCell>
            <TableCell>{can("template.show") && api.showTemplate && <Button type="button" variant="ghost" size="sm" aria-label={t("tp.showLabel", { id: item.id })} onClick={() => setShown(item.id)}>{t("tp.show")}</Button>}</TableCell>
          </TableRow>)}</TableBody>
        </Table>}</QueryBoundary>}
      {shown && <section aria-label={t("tp.structure")} className="grid gap-2 rounded-lg border bg-card p-4">
        <h3 className="text-lg font-semibold">{shown}</h3>
        <QueryBoundary query={detail} skeleton="h-16 w-full">{data => <StructureView value={data.template} />}</QueryBoundary>
      </section>}
    </section>

    <section aria-label={t("tp.catalogLabel")} className="grid gap-3">
      <h2 className="text-xl font-semibold">{t("tp.catalog")}</h2>
      {!listable || !api.listTemplateCatalog ? <Unavailable>{t("tp.catalogUnavailable")}</Unavailable>
        : <QueryBoundary query={catalog} skeleton="h-16 w-full">{entries => <Table aria-label={t("tp.catalog")}>
          <TableHeader><TableRow><TableHead>{t("tp.template")}</TableHead><TableHead>{t("tp.state")}</TableHead><TableHead className="w-32"><span className="sr-only">{t("tp.actions")}</span></TableHead></TableRow></TableHeader>
          <TableBody>{entries.map(item => <TableRow key={item.name}>
            <TableCell className="font-medium">{item.name}</TableCell>
            <TableCell><Badge variant={item.installed ? "secondary" : "outline"}>{item.installed ? t("tp.installed") : t("tp.notInstalled")}</Badge></TableCell>
            <TableCell>{can("template.use") && api.installBuiltinTemplate && <Button type="button" variant="outline" size="sm" aria-label={t("tp.installLabel", { name: item.name })} disabled={install.isPending} onClick={() => install.mutate({ name: item.name, force: false })}>{item.installed ? t("tp.reinstall") : t("tp.install")}</Button>}</TableCell>
          </TableRow>)}</TableBody>
        </Table>}</QueryBoundary>}
      {!exists && <ActionError action={install} what={t("act.installTemplate")} />}
      <ConfirmActionDialog open={exists} title={t("tp.replaceTitle", { name: install.variables?.name ?? t("tp.replaceDefault") })}
        description={t("tp.replaceBody")}
        confirmLabel={t("tp.replaceConfirm")} pending={install.isPending}
        onOpenChange={open => { if (!open) install.reset(); }} onConfirm={() => install.variables && install.mutate({ name: install.variables.name, force: true })} />
    </section>

    {canCreate && <section aria-label={t("tp.createLabel")} className="grid gap-3">
      <h2 className="text-xl font-semibold">{t("tp.createHeading")}</h2>
      <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); if (newName.trim()) create.mutate(newName.trim()); }}>
        <div className="grid gap-1"><Label htmlFor="new-template">{t("tp.newName")}</Label><Input id="new-template" autoComplete="off" value={newName} onChange={event => setNewName(event.target.value)} /></div>
        <Button type="submit" disabled={!newName.trim() || create.isPending}>{t("tp.create")}</Button>
      </form>
      <ActionError action={create} what={t("act.createTemplate")} />
    </section>}

    {can("template.validate") && api.validateTemplate && <TemplateValidationPanel initialName={shown ?? ""} />}
  </div>;
}
