import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import type { RevisionInput, RevisionResult } from "@/api/domains/authoring";
import { ActionError, Unavailable, authoringKeys, errorText, useAction, useCapability } from "./data";

/** Readable detail: scalars and lists of scalars only; nested structures are skipped rather than dumped as JSON. */
function RevisionDetail({ detail }: { detail: Record<string, unknown> }) {
  const rows = Object.entries(detail).flatMap(([key, value]): Array<[string, string[]]> => {
    if (["string", "number", "boolean"].includes(typeof value)) return [[key, [String(value)]]];
    if (Array.isArray(value) && value.every(entry => ["string", "number"].includes(typeof entry))) return [[key, value.map(String)]];
    return [];
  });
  return <dl className="grid gap-2 text-sm sm:grid-cols-[8rem_1fr]">{rows.map(([key, values]) => <div key={key} className="contents"><dt className="font-medium">{key}</dt><dd>{values.length === 1 ? values[0] : <ul>{values.map(entry => <li key={entry}>{entry}</li>)}</ul>}</dd></div>)}</dl>;
}

function ReviseDialog({ documentId, open, onOpenChange }: { documentId: string; open: boolean; onOpenChange(open: boolean): void }) {
  const api = useApi();
  const [target, setTarget] = useState("");
  const [body, setBody] = useState("");
  const [value, setValue] = useState("");
  const [field, setField] = useState("");
  const [strict, setStrict] = useState(false);
  const revise = useAction(
    (): Promise<RevisionResult> => {
      const input: RevisionInput = { target_id: target.trim(), ...(body ? { new_body: body } : {}), ...(value ? { new_value: value } : {}), ...(field.trim() ? { field: field.trim() } : {}), ...(strict ? { strict: true } : {}) };
      return api.reviseDocument!(documentId, input);
    },
    { success: result => `Revised ${result.target_id}.`, invalidate: [authoringKeys.sections(documentId), authoringKeys.revisions()] },
  );
  return <Dialog open={open} onOpenChange={next => { if (!next) revise.reset(); onOpenChange(next); }}>
    <DialogContent><DialogHeader><DialogTitle>Revise document</DialogTitle><DialogDescription>Replace the body of a section, or a context value. The server records a revision with its diff.</DialogDescription></DialogHeader>
      <form className="grid gap-3" onSubmit={event => { event.preventDefault(); revise.mutate(undefined); }}>
        <div className="grid gap-1"><Label htmlFor="revise-target">Target</Label><Input id="revise-target" value={target} onChange={event => setTarget(event.target.value)} required /></div>
        <div className="grid gap-1"><Label htmlFor="revise-body">New body</Label><Textarea id="revise-body" value={body} onChange={event => setBody(event.target.value)} /></div>
        <div className="grid gap-1"><Label htmlFor="revise-value">New value</Label><Input id="revise-value" value={value} onChange={event => setValue(event.target.value)} /></div>
        <div className="grid gap-1"><Label htmlFor="revise-field">Field</Label><Input id="revise-field" value={field} onChange={event => setField(event.target.value)} /></div>
        <div className="flex items-center gap-2"><Checkbox id="revise-strict" checked={strict} onCheckedChange={checked => setStrict(checked === true)} /><Label htmlFor="revise-strict">Strict</Label></div>
        <ActionError action={revise} what="revise the document" />
        {revise.data && <section aria-label="Revision result" className="grid gap-2 rounded-md border p-3 text-sm"><p className="font-medium">{revise.data.summary}</p>
          {revise.data.changed_sections.length > 0 && <p>Changed sections: {revise.data.changed_sections.join(", ")}</p>}
          <pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs whitespace-pre-wrap">{revise.data.diff}</pre></section>}
        <DialogFooter><Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Close</Button><Button type="submit" disabled={!target.trim() || (!body && !value) || revise.isPending}>Apply revision</Button></DialogFooter>
      </form></DialogContent>
  </Dialog>;
}

export function RevisionsPanel({ documentId }: { documentId: string }) {
  const api = useApi();
  const can = useCapability();
  const [reviseOpen, setReviseOpen] = useState(false);
  const list = useQuery({ queryKey: authoringKeys.revisions(), queryFn: () => api.listRevisions(), enabled: can("revisions.list") });
  const open = useAction((id: string) => api.getRevision!(id).then(detail => ({ id, detail })), { success: result => `Loaded revision ${result.id}.` });
  return <div className="grid gap-6">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-xl font-semibold">Revisions</h2>
      {can("doc.revise") && api.reviseDocument ? <Button type="button" onClick={() => setReviseOpen(true)}>Revise document</Button> : <Unavailable>Revising is not available on this server.</Unavailable>}</div>
    {!can("revisions.list") ? <Unavailable>Revisions are not available on this server.</Unavailable> : list.isPending ? <Skeleton className="h-24 w-full" /> : list.isError ? <ErrorState message={errorText(list.error, "revisions")} onRetry={() => void list.refetch()} />
      : list.data.length === 0 ? <EmptyState title="No revisions yet" description="Saving a section or revising the document records a revision here." />
      : <ol aria-label="Revision timeline" className="grid gap-3 border-l pl-4">{list.data.map(item => <li key={item.id} className="grid gap-1">
        <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{item.message}</span><Badge variant="outline">{item.status}</Badge></div>
        <p className="text-sm text-muted-foreground">{item.author} · {item.date} · {item.files} files</p>
        {api.getRevision && <Button type="button" variant="ghost" size="sm" className="w-fit" aria-label={`View revision ${item.id}`} onClick={() => open.mutate(item.id)}>View</Button>}</li>)}</ol>}
    <ActionError action={open} what="load the revision" />
    {open.data && <section aria-label={`Revision ${open.data.id}`} className="rounded-lg border bg-card p-4"><h3 className="mb-2 font-semibold">Revision {open.data.id}</h3><RevisionDetail detail={open.data.detail} /></section>}
    <ReviseDialog documentId={documentId} open={reviseOpen} onOpenChange={setReviseOpen} />
  </div>;
}
