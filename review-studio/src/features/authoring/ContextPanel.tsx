import { useT } from "@/lib/i18n";
import { useState } from "react";
import { useApi } from "@/app/providers";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { EmptyState } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ActionError, useAction } from "@/lib/actions";
import { Unavailable } from "@/components/shared/Unavailable";
import { useCapability } from "@/lib/capability-registry";
import { authoringKeys, useContextStatus } from "./data";

export function ContextPanel({ documentId }: { documentId: string }) {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const status = useContextStatus(documentId);
  const [topic, setTopic] = useState("");
  const [field, setField] = useState("");
  const [value, setValue] = useState("");
  const [shown, setShown] = useState<{ topic: string; content: string } | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const invalidate = [authoringKeys.context(documentId)];

  const set = useAction(() => api.setDocumentContext!(documentId, { topic: topic.trim(), ...(field.trim() ? { field: field.trim() } : {}), value }), { success: () => t("ctx.saved", { topic: topic.trim() }), invalidate, onDone: () => setValue("") });
  const show = useAction((id: string) => api.showContextTopic!(documentId, id), { success: result => t("ctx.loaded", { topic: result.topic }), onDone: result => setShown({ topic: result.topic, content: result.content }) });
  const remove = useAction((id: string) => api.removeContextTopic!(documentId, id), { success: result => t("ctx.removed", { topic: result.removed }), invalidate, onDone: () => setRemoving(null) });
  const elicit = useAction(() => api.elicitContext!(documentId, topic.trim()), { success: result => t("ctx.questionnaireToast", { path: result.path }) });
  const ingest = useAction(() => api.ingestContext!(documentId), { success: result => t("ctx.ingested", { count: result.topics.length }), invalidate });

  return <div className="grid gap-6">
    <h2 className="text-xl font-semibold">{t("ctx.heading")}</h2>
    {!can("context.status") ? <Unavailable>{t("ctx.unavailableStatus")}</Unavailable>
      : <QueryBoundary query={status}>{({ topics }) => topics.length === 0 ? <EmptyState title={t("ctx.none.title")} description={t("ctx.none.body")} action={{ label: t("empty.reviewTemplates"), to: "/configure/templates" }} />
      : <ul className="grid gap-3 sm:grid-cols-2" aria-label={t("ctx.topicsLabel")}>{topics.map(item => <li key={item.id}><Card>
        <CardHeader><CardTitle className="flex flex-wrap items-center gap-2 text-base"><span>{item.title}</span>
          <Badge variant={item.missing ? "destructive" : "secondary"}>{item.missing ? t("ctx.missing") : t("ctx.ready")}</Badge>{item.required && <Badge variant="outline">{t("ctx.required")}</Badge>}</CardTitle></CardHeader>
        <CardContent className="grid gap-2">
          {item.fields.length > 0 && <p className="text-sm text-muted-foreground">{t("ctx.fields", { fields: item.fields.map(entry => entry.label).join(", ") })}</p>}
          <div className="flex flex-wrap gap-2">
            {can("context.set") && <Button type="button" size="sm" variant="outline" aria-label={t("ctx.setValueLabel", { id: item.id })} onClick={() => { setTopic(item.id); setField(item.fields[0]?.key ?? ""); }}>{t("ctx.setValue")}</Button>}
            {item.exists && can("context.show") && <Button type="button" size="sm" variant="ghost" aria-label={t("ctx.viewLabel", { id: item.id })} disabled={show.isPending} onClick={() => show.mutate(item.id)}>{t("ctx.view")}</Button>}
            {item.exists && can("context.rm") && <Button type="button" size="sm" variant="ghost" aria-label={t("ctx.removeLabel", { id: item.id })} onClick={() => { remove.reset(); setRemoving(item.id); }}>{t("ctx.remove")}</Button>}
          </div></CardContent></Card></li>)}</ul>}</QueryBoundary>}
    <ActionError action={show} what={t("act.loadTopic")} />
    {shown && <section aria-label={t("ctx.topicLabel", { topic: shown.topic })} className="rounded-lg border bg-card p-4"><h3 className="font-semibold">{shown.topic}</h3><pre className="mt-2 text-sm whitespace-pre-wrap">{shown.content}</pre></section>}

    {can("context.set") && api.setDocumentContext ? <form className="grid max-w-xl gap-3" onSubmit={event => { event.preventDefault(); set.mutate(undefined); }}>
      <div className="grid gap-1"><Label htmlFor="context-topic">{t("ctx.topic")}</Label><Input id="context-topic" value={topic} onChange={event => setTopic(event.target.value)} /></div>
      <div className="grid gap-1"><Label htmlFor="context-field">{t("ctx.field")}</Label><Input id="context-field" value={field} onChange={event => setField(event.target.value)} /></div>
      <div className="grid gap-1"><Label htmlFor="context-value">{t("ctx.value")}</Label><Textarea id="context-value" value={value} onChange={event => setValue(event.target.value)} /></div>
      <Button type="submit" className="w-fit" disabled={set.isPending || !topic.trim() || !value.trim()}>{t("ctx.setContextValue")}</Button>
    </form> : <Unavailable>{t("ctx.unavailableSet")}</Unavailable>}
    <ActionError action={set} what={t("act.saveContext")} />

    <div className="flex flex-wrap gap-2">
      {can("context.elicit") && api.elicitContext && <Button type="button" variant="outline" disabled={elicit.isPending} onClick={() => elicit.mutate(undefined)}>{t("ctx.writeQuestionnaire")}</Button>}
      {can("context.ingest") && api.ingestContext && <Button type="button" variant="outline" disabled={ingest.isPending} onClick={() => ingest.mutate(undefined)}>{t("ctx.ingestAnswers")}</Button>}
    </div>
    <ActionError action={elicit} what={t("act.writeQuestionnaire")} />
    {elicit.data && <section aria-label={t("ctx.questionnaire")} className="rounded-lg border bg-card p-4"><h3 className="font-semibold">{t("ctx.questionnaireWritten", { path: elicit.data.path })}</h3><pre className="mt-2 text-sm whitespace-pre-wrap">{elicit.data.markdown}</pre></section>}
    <ActionError action={ingest} what={t("act.ingestAnswers")} />
    {ingest.data && <p role="status" className="text-sm">{t("ctx.topicsAvailable", { topics: ingest.data.topics.join(", ") || t("common.none") })}</p>}

    <ConfirmActionDialog open={removing !== null} title={t("ctx.removeTitle", { id: removing ?? "" })} description={t("ctx.removeBody")}
      confirmLabel={t("ctx.removeConfirm")} pending={remove.isPending} error={remove.error}
      onOpenChange={open => { if (!open) setRemoving(null); }} onConfirm={() => removing && remove.mutate(removing)} />
  </div>;
}
