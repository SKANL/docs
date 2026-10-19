import { focusTargets } from "@/lib/focus-targets";
import { useT } from "@/lib/i18n";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/app/providers";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { EmptyState, focusById } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ActionError, useAction } from "@/lib/actions";
import { Unavailable } from "@/components/shared/Unavailable";
import { fileToBase64 } from "@/lib/files";
import { useCapability } from "@/lib/capability-registry";
import { authoringKeys } from "./data";

export function AssetsPanel({ documentId }: { documentId: string }) {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const [kindDraft, setKindDraft] = useState("");
  const [kind, setKind] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [removing, setRemoving] = useState<string | null>(null);
  const list = useQuery({ queryKey: [...authoringKeys.assets(documentId), kind], queryFn: () => api.listAssets!(documentId, kind || undefined), enabled: !!api.listAssets && can("asset.list") });
  const invalidate = [authoringKeys.assets(documentId)];
  const add = useAction(
    async () => api.addAsset!(documentId, { filename: file!.name, contentBase64: await fileToBase64(file!), ...(name.trim() ? { name: name.trim() } : {}) }),
    { success: result => t("asset.added", { name: result.name }), invalidate, onDone: () => { setFile(null); setName(""); } },
  );
  const remove = useAction((asset: string) => api.removeAsset!(documentId, asset), { success: result => t("asset.removed", { name: result.removed }), invalidate, onDone: () => setRemoving(null) });

  return <div className="grid gap-6">
    <h2 className="text-xl font-semibold">{t("asset.heading")}</h2>
    {can("asset.list") && api.listAssets && <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); setKind(kindDraft.trim()); }}>
      <div className="grid gap-1"><Label htmlFor="asset-kind">{t("asset.filter")}</Label><Input id="asset-kind" value={kindDraft} onChange={event => setKindDraft(event.target.value)} placeholder={t("asset.filterPlaceholder")} /></div>
      <Button type="submit" variant="outline">{t("asset.apply")}</Button>
    </form>}
    {!(can("asset.list") && api.listAssets) ? <Unavailable>{t("asset.unavailableList")}</Unavailable>
      : <QueryBoundary query={list}>{({ items }) => items.length === 0 ? <EmptyState title={t("asset.none.title")} description={kind ? t("asset.none.kind", { kind }) : t("asset.none.body")} action={{ label: t("empty.addAsset"), onClick: focusById(focusTargets.assetFile) }} />
      : <Table aria-label={t("asset.tableLabel")}><TableHeader><TableRow><TableHead>{t("asset.name")}</TableHead><TableHead className="w-24"><span className="sr-only">{t("asset.actions")}</span></TableHead></TableRow></TableHeader>
        <TableBody>{items.map(item => <TableRow key={item.name}><TableCell>{item.name}</TableCell>
          <TableCell>{can("asset.rm") && <Button type="button" variant="ghost" size="sm" aria-label={t("asset.removeLabel", { name: item.name })} onClick={() => { remove.reset(); setRemoving(item.name); }}>{t("asset.remove")}</Button>}</TableCell></TableRow>)}</TableBody></Table>}</QueryBoundary>}
    {can("asset.add") && api.addAsset ? <form className="grid max-w-xl gap-3" onSubmit={event => { event.preventDefault(); if (file) add.mutate(undefined); }}>
      <div className="grid gap-1"><Label htmlFor={focusTargets.assetFile}>{t("asset.file")}</Label><Input id={focusTargets.assetFile} type="file" onChange={event => setFile(event.target.files?.[0] ?? null)} /></div>
      <div className="grid gap-1"><Label htmlFor="asset-name">{t("asset.nameOptional")}</Label><Input id="asset-name" value={name} onChange={event => setName(event.target.value)} /></div>
      <Button type="submit" className="w-fit" disabled={!file || add.isPending}>{add.isPending ? t("asset.adding") : t("asset.add")}</Button>
    </form> : <Unavailable>{t("asset.unavailableAdd")}</Unavailable>}
    <ActionError action={add} what={t("act.addAsset")} />
    <ConfirmActionDialog open={removing !== null} title={t("asset.removeTitle", { name: removing ?? t("asset.removeUnnamed") })} description={t("asset.removeBody")}
      confirmLabel={t("asset.removeConfirm")} pending={remove.isPending} error={remove.error}
      onOpenChange={open => { if (!open) setRemoving(null); }} onConfirm={() => removing && remove.mutate(removing)} />
  </div>;
}
