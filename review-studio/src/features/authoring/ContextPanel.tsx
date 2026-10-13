import { formatApiError } from "@/api/errors";
import { useState } from "react";
import { useApi } from "@/app/providers";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ActionError, useAction } from "@/lib/actions";
import { Unavailable } from "@/components/shared/Unavailable";
import { useCapability } from "@/lib/capability-registry";
import { authoringKeys, useContextStatus } from "./data";

export function ContextPanel({ documentId }: { documentId: string }) {
  const api = useApi();
  const can = useCapability();
  const status = useContextStatus(documentId);
  const [topic, setTopic] = useState("");
  const [field, setField] = useState("");
  const [value, setValue] = useState("");
  const [shown, setShown] = useState<{ topic: string; content: string } | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const invalidate = [authoringKeys.context(documentId)];

  const set = useAction(() => api.setDocumentContext!(documentId, { topic: topic.trim(), ...(field.trim() ? { field: field.trim() } : {}), value }), { success: () => `Saved context for ${topic.trim()}.`, invalidate, onDone: () => setValue("") });
  const show = useAction((id: string) => api.showContextTopic!(documentId, id), { success: result => `Loaded topic ${result.topic}.`, onDone: result => setShown({ topic: result.topic, content: result.content }) });
  const remove = useAction((id: string) => api.removeContextTopic!(documentId, id), { success: result => `Removed topic ${result.removed}.`, invalidate, onDone: () => setRemoving(null) });
  const elicit = useAction(() => api.elicitContext!(documentId, topic.trim()), { success: result => `Questionnaire written to ${result.path}.` });
  const ingest = useAction(() => api.ingestContext!(documentId), { success: result => `Ingested ${result.topics.length} topics.`, invalidate });

  return <div className="grid gap-6">
    <h2 className="text-xl font-semibold">Context</h2>
    {!can("context.status") ? <Unavailable>Context status is not available on this server.</Unavailable>
      : status.isPending ? <Skeleton className="h-24 w-full" />
      : status.isError ? <ErrorState message={formatApiError(status.error)} onRetry={() => void status.refetch()} />
      : status.data.topics.length === 0 ? <EmptyState title="No context topics" description="The template declares no context topics for this document." />
      : <ul className="grid gap-3 sm:grid-cols-2" aria-label="Context topics">{status.data.topics.map(item => <li key={item.id}><Card>
        <CardHeader><CardTitle className="flex flex-wrap items-center gap-2 text-base"><span>{item.title}</span>
          <Badge variant={item.missing ? "destructive" : "secondary"}>{item.missing ? "Missing" : "Ready"}</Badge>{item.required && <Badge variant="outline">Required</Badge>}</CardTitle></CardHeader>
        <CardContent className="grid gap-2">
          {item.fields.length > 0 && <p className="text-sm text-muted-foreground">Fields: {item.fields.map(entry => entry.label).join(", ")}</p>}
          <div className="flex flex-wrap gap-2">
            {can("context.set") && <Button type="button" size="sm" variant="outline" aria-label={`Set value for ${item.id}`} onClick={() => { setTopic(item.id); setField(item.fields[0]?.key ?? ""); }}>Set value</Button>}
            {item.exists && can("context.show") && <Button type="button" size="sm" variant="ghost" aria-label={`View ${item.id}`} disabled={show.isPending} onClick={() => show.mutate(item.id)}>View</Button>}
            {item.exists && can("context.rm") && <Button type="button" size="sm" variant="ghost" aria-label={`Remove ${item.id}`} onClick={() => { remove.reset(); setRemoving(item.id); }}>Remove</Button>}
          </div></CardContent></Card></li>)}</ul>}
    <ActionError action={show} what="load the topic" />
    {shown && <section aria-label={`Topic ${shown.topic}`} className="rounded-lg border bg-card p-4"><h3 className="font-semibold">{shown.topic}</h3><pre className="mt-2 text-sm whitespace-pre-wrap">{shown.content}</pre></section>}

    {can("context.set") && api.setDocumentContext ? <form className="grid max-w-xl gap-3" onSubmit={event => { event.preventDefault(); set.mutate(undefined); }}>
      <div className="grid gap-1"><Label htmlFor="context-topic">Topic</Label><Input id="context-topic" value={topic} onChange={event => setTopic(event.target.value)} /></div>
      <div className="grid gap-1"><Label htmlFor="context-field">Field</Label><Input id="context-field" value={field} onChange={event => setField(event.target.value)} /></div>
      <div className="grid gap-1"><Label htmlFor="context-value">Value</Label><Textarea id="context-value" value={value} onChange={event => setValue(event.target.value)} /></div>
      <Button type="submit" className="w-fit" disabled={set.isPending || !topic.trim() || !value.trim()}>Set context value</Button>
    </form> : <Unavailable>Setting context values is not available on this server.</Unavailable>}
    <ActionError action={set} what="save the context value" />

    <div className="flex flex-wrap gap-2">
      {can("context.elicit") && api.elicitContext && <Button type="button" variant="outline" disabled={elicit.isPending} onClick={() => elicit.mutate(undefined)}>Write questionnaire</Button>}
      {can("context.ingest") && api.ingestContext && <Button type="button" variant="outline" disabled={ingest.isPending} onClick={() => ingest.mutate(undefined)}>Ingest answers</Button>}
    </div>
    <ActionError action={elicit} what="write the questionnaire" />
    {elicit.data && <section aria-label="Questionnaire" className="rounded-lg border bg-card p-4"><h3 className="font-semibold">Questionnaire written to {elicit.data.path}</h3><pre className="mt-2 text-sm whitespace-pre-wrap">{elicit.data.markdown}</pre></section>}
    <ActionError action={ingest} what="ingest the answers" />
    {ingest.data && <p role="status" className="text-sm">Topics now available: {ingest.data.topics.join(", ") || "none"}.</p>}

    <ConfirmActionDialog open={removing !== null} title={`Remove topic ${removing ?? ""}?`} description="The saved answers for this topic are deleted. You can write the questionnaire again afterwards."
      confirmLabel="Remove topic" pending={remove.isPending} error={remove.isError ? formatApiError(remove.error) : undefined}
      onOpenChange={open => { if (!open) setRemoving(null); }} onConfirm={() => removing && remove.mutate(removing)} />
  </div>;
}
