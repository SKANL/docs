import { formatApiError } from "@/api/errors";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/app/providers";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ActionError, useAction } from "@/lib/actions";
import { Unavailable } from "@/components/shared/Unavailable";
import { fileToBase64 } from "@/lib/files";
import { useCapability } from "@/lib/capability-registry";
import { authoringKeys } from "./data";

export function AssetsPanel({ documentId }: { documentId: string }) {
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
    { success: result => `Added asset ${result.name}.`, invalidate, onDone: () => { setFile(null); setName(""); } },
  );
  const remove = useAction((asset: string) => api.removeAsset!(documentId, asset), { success: result => `Removed asset ${result.removed}.`, invalidate, onDone: () => setRemoving(null) });

  return <div className="grid gap-6">
    <h2 className="text-xl font-semibold">Assets</h2>
    {can("asset.list") && api.listAssets && <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); setKind(kindDraft.trim()); }}>
      <div className="grid gap-1"><Label htmlFor="asset-kind">Filter by kind</Label><Input id="asset-kind" value={kindDraft} onChange={event => setKindDraft(event.target.value)} placeholder="e.g. images" /></div>
      <Button type="submit" variant="outline">Apply filter</Button>
    </form>}
    {list.isPending ? (can("asset.list") ? <Skeleton className="h-24 w-full" /> : <Unavailable>Listing assets is not available on this server.</Unavailable>)
      : list.isError ? <ErrorState message={formatApiError(list.error)} onRetry={() => void list.refetch()} />
      : list.data.items.length === 0 ? <EmptyState title="No assets" description={kind ? `No assets of kind "${kind}".` : "Add logos, images, or other files the document uses."} />
      : <Table aria-label="Document assets"><TableHeader><TableRow><TableHead>Name</TableHead><TableHead className="w-24"><span className="sr-only">Actions</span></TableHead></TableRow></TableHeader>
        <TableBody>{list.data.items.map(item => <TableRow key={item.name}><TableCell>{item.name}</TableCell>
          <TableCell>{can("asset.rm") && <Button type="button" variant="ghost" size="sm" aria-label={`Remove ${item.name}`} onClick={() => { remove.reset(); setRemoving(item.name); }}>Remove</Button>}</TableCell></TableRow>)}</TableBody></Table>}
    {can("asset.add") && api.addAsset ? <form className="grid max-w-xl gap-3" onSubmit={event => { event.preventDefault(); if (file) add.mutate(undefined); }}>
      <div className="grid gap-1"><Label htmlFor="asset-file">Asset file</Label><Input id="asset-file" type="file" onChange={event => setFile(event.target.files?.[0] ?? null)} /></div>
      <div className="grid gap-1"><Label htmlFor="asset-name">Asset name (optional)</Label><Input id="asset-name" value={name} onChange={event => setName(event.target.value)} /></div>
      <Button type="submit" className="w-fit" disabled={!file || add.isPending}>{add.isPending ? "Adding…" : "Add asset"}</Button>
    </form> : <Unavailable>Adding assets is not available on this server.</Unavailable>}
    <ActionError action={add} what="add the asset" />
    <ConfirmActionDialog open={removing !== null} title={`Remove ${removing ?? "asset"}?`} description="The file is deleted from the document. Sections that reference it will show a finding at the next review."
      confirmLabel="Remove asset" pending={remove.isPending} error={remove.isError ? formatApiError(remove.error) : undefined}
      onOpenChange={open => { if (!open) setRemoving(null); }} onConfirm={() => removing && remove.mutate(removing)} />
  </div>;
}
