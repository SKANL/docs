import { useT } from "@/lib/i18n";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApi } from "@/app/providers";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { EmptyState } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ContextPacked, ReviewFinding, ReviewResult } from "@/api/domains/authoring";
import { ActionError, useAction } from "@/lib/actions";
import { useCapability } from "@/lib/capability-registry";
import { useMode } from "@/app/mode";
import { authoringKeys, useSections } from "./data";

function ReviewFindingsPanel({ result, onOpenSection }: { result: ReviewResult; onOpenSection(id: string): void }) {
  const { t } = useT();
  const where = (finding: ReviewFinding) => [finding.section && t("sec.whereSection", { id: finding.section }), finding.file, finding.page != null && t("sec.wherePage", { page: finding.page })].filter(Boolean).join(" · ");
  return <section aria-label={t("sec.findings")} className="grid gap-3 rounded-lg border bg-card p-4">
    <div className="flex items-center gap-2"><h3 className="font-semibold">{t("sec.findings")}</h3><Badge variant={result.passed ? "secondary" : "destructive"}>{result.passed ? t("status.passed") : t("doc.needsAttention")}</Badge>
      <span className="text-sm text-muted-foreground">{result.section_id ? t("sec.sectionOf", { id: result.section_id }) : t("sec.wholeDocument")}</span></div>
    {result.findings.length === 0 ? <p className="text-sm text-muted-foreground">{t("sec.noFindings")}</p>
      : <ul className="grid gap-2">{result.findings.map((finding, index) => <li key={`${finding.code}-${index}`} className="grid gap-1 rounded-md border p-3 text-sm">
        <div className="flex flex-wrap items-center gap-2"><Badge variant={finding.severity === "low" ? "outline" : "destructive"}>{finding.severity}</Badge><code className="text-xs">{finding.code}</code><span className="text-muted-foreground">{finding.dimension}</span></div>
        <p>{finding.message}</p>
        {where(finding) && <p className="text-muted-foreground">{where(finding)}</p>}
        {finding.resolution_condition && <p className="text-muted-foreground">{t("sec.toResolve", { condition: finding.resolution_condition })}</p>}
        {finding.section && <Button type="button" variant="outline" size="sm" className="w-fit" aria-label={t("sec.fixInLabel", { id: finding.section })} onClick={() => onOpenSection(finding.section!)}>{t("sec.fixIn")}</Button>}
      </li>)}</ul>}
  </section>;
}

export function SectionsPanel({ documentId }: { documentId: string }) {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const { mode, advanced } = useMode();
  const sections = useSections(documentId);
  // `?section=` lets a review finding open the section it points at.
  const [params] = useSearchParams();
  const [selected, setSelected] = useState<string | null>(params.get("section"));
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<{ id: string; focus: boolean } | null>(null);
  const [review, setReview] = useState<ReviewResult | null>(null);
  const [packed, setPacked] = useState<ContextPacked | null>(null);
  // Supervise leans on reading and reviewing: the body is read-only until the person asks to edit it.
  const [editing, setEditing] = useState(false);
  const [editingScope, setEditingScope] = useState("");
  const [stampOpen, setStampOpen] = useState(false);
  const [packOpen, setPackOpen] = useState(false);
  const [by, setBy] = useState("");
  const [model, setModel] = useState("");
  const [target, setTarget] = useState("all");
  const editor = useRef<HTMLTextAreaElement>(null);
  const focusAfterSelect = useRef(false);

  const items = sections.data ?? [];
  const activeId = selected ?? items[0]?.id ?? null;
  const active = items.find(item => item.id === activeId);
  // Editing lapses when the document, working mode or section changes (state reset during render, no effect).
  const scope = `${documentId}|${mode}|${activeId}`;
  if (scope !== editingScope) { setEditingScope(scope); setEditing(false); }
  const draft = activeId ? drafts[activeId] : undefined;
  const body = draft ?? active?.body ?? "";
  const dirty = (id: string) => drafts[id] !== undefined && drafts[id] !== items.find(item => item.id === id)?.body;
  const anyDirty = items.some(item => dirty(item.id));
  const editable = mode === "write" || editing || anyDirty;

  useEffect(() => {
    if (focusAfterSelect.current) { focusAfterSelect.current = false; editor.current?.focus(); }
  }, [activeId]);
  useEffect(() => {
    if (!anyDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    addEventListener("beforeunload", warn);
    return () => removeEventListener("beforeunload", warn);
  }, [anyDirty]);

  const discard = (id: string) => setDrafts(({ [id]: _dropped, ...rest }) => rest);
  const apply = (id: string, focus: boolean) => {
    if (focus) { if (id === activeId) editor.current?.focus(); else focusAfterSelect.current = true; }
    // Section-bound results must not survive a switch: a stale retry would target the new section.
    if (id !== activeId) { save.reset(); build.reset(); reviewSection.reset(); stamp.reset(); }
    setSelected(id);
  };
  const open = (id: string, focus = false) => {
    if (id !== activeId && activeId && dirty(activeId)) setPending({ id, focus });
    else apply(id, focus);
  };

  const invalidate = [authoringKeys.sections(documentId)];
  // The target section travels in the mutation variables so a retry replays the same target and text.
  const save = useAction(({ id, text }: { id: string; text: string }) => api.updateDocumentSection!(documentId, id, text), { success: (_result, { id }) => t("sec.saved", { id }), invalidate, onDone: (_result, { id }) => discard(id) });
  const build = useAction((id: string) => api.buildSection!(documentId, id), { success: result => t("sec.built", { path: result.path }), invalidate });
  const reviewSection = useAction((id: string) => api.reviewSection!(documentId, id), { success: result => result.passed ? t("sec.reviewPassed") : t("sec.reviewIssues"), onDone: setReview });
  const reviewDocument = useAction(() => api.reviewDocument!(documentId), { success: result => result.passed ? t("sec.docReviewPassed") : t("sec.docReviewIssues"), onDone: setReview });
  const stamp = useAction((id: string) => api.stampSection!(documentId, id, { by: by.trim(), ...(model.trim() ? { model: model.trim() } : {}) }), { success: result => t("sec.stamped", { id: result.section_id, by: result.authored_by }), onDone: () => setStampOpen(false) });
  const pack = useAction(() => api.packContext!(documentId, target.trim()), { success: result => t("sec.packed", { target: result.target }), onDone: result => { setPacked(result); setPackOpen(false); } });

  return <QueryBoundary query={sections} skeleton="h-48 w-full">{() => items.length === 0
    ? <EmptyState title={t("sec.none.title")} description={t("sec.none.body")} action={{ label: t("empty.uploadSources"), to: "/authoring/sources" }} />
    : <div className="grid gap-6">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-xl font-semibold">{t("au.tab.sections")}</h2>
        <div className="flex flex-wrap gap-2">
          {can("review-document") && api.reviewDocument && <Button type="button" variant="outline" disabled={reviewDocument.isPending} onClick={() => reviewDocument.mutate(undefined)}>{t("sec.reviewDocument")}</Button>}
          {advanced && can("pack-context") && api.packContext && <Button type="button" variant="outline" onClick={() => { pack.reset(); setPackOpen(true); }}>{t("sec.packContext")}</Button>}
        </div></div>
      <ActionError action={reviewDocument} what={t("act.reviewDocument")} />
      <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
        <nav aria-label={t("au.tab.sections")}><ul className="grid gap-1">{items.map(item => <li key={item.id}>
          <Button type="button" variant={item.id === activeId ? "secondary" : "ghost"} className="w-full justify-between" aria-current={item.id === activeId ? "true" : undefined} onClick={() => open(item.id)}>
            <span>{item.id}</span>{dirty(item.id) && <Badge variant="outline">{t("sec.unsaved")}</Badge>}</Button></li>)}</ul></nav>
        <div className="grid gap-3">
          <Label htmlFor="section-body">{t("sec.body")}</Label>
          <Textarea id="section-body" ref={editor} rows={14} value={body} readOnly={!editable} onChange={event => activeId && setDrafts(current => ({ ...current, [activeId]: event.target.value }))} />
          <div className="flex flex-wrap gap-2">
            {editable
              ? <Button type="button" variant={mode === "write" ? "default" : "outline"} disabled={!activeId || !dirty(activeId) || save.isPending} onClick={() => save.mutate({ id: activeId!, text: body })}>{save.isPending ? t("common.saving") : t("sec.save")}</Button>
              : <Button type="button" variant="outline" onClick={() => { setEditing(true); editor.current?.focus(); }}>{t("sections.edit")}</Button>}
            {can("review-section") && api.reviewSection && <Button type="button" variant={mode === "supervise" ? "default" : "outline"} disabled={reviewSection.isPending} onClick={() => reviewSection.mutate(activeId!)}>{t("sec.review")}</Button>}
            {advanced && can("build-section") && api.buildSection && <Button type="button" variant="outline" disabled={build.isPending} onClick={() => build.mutate(activeId!)}>{t("sec.build")}</Button>}
            {advanced && can("stamp-section") && api.stampSection && <Button type="button" variant="outline" onClick={() => { stamp.reset(); setStampOpen(true); }}>{t("sec.stamp")}</Button>}
          </div>
          <ActionError action={save} what={t("act.saveSection")} />
          <ActionError action={build} what={t("act.buildSection")} />
          <ActionError action={reviewSection} what={t("act.reviewSection")} />
        </div>
      </div>
      {packed && <section aria-label={t("sec.packedLabel")} className="rounded-lg border bg-card p-4"><h3 className="font-semibold">{t("sec.packedFor", { target: packed.target })}</h3><ul className="mt-2 list-disc pl-5 text-sm">{packed.paths.map(path => <li key={path}>{path}</li>)}</ul></section>}
      {review && <ReviewFindingsPanel result={review} onOpenSection={id => open(id, true)} />}

      <ConfirmActionDialog open={pending !== null} title={t("sec.discardTitle")} description={t("sec.discardBody", { id: activeId ?? "" })} confirmLabel={t("sec.discard")}
        onOpenChange={next => { if (!next) setPending(null); }} onConfirm={() => { if (pending && activeId) { discard(activeId); apply(pending.id, pending.focus); } setPending(null); }} />

      <Dialog open={stampOpen} onOpenChange={setStampOpen}>
        <DialogContent><DialogHeader><DialogTitle>{t("sec.stampTitle", { id: activeId ?? "" })}</DialogTitle><DialogDescription>{t("sec.stampBody")}</DialogDescription></DialogHeader>
          <form className="grid gap-3" onSubmit={event => { event.preventDefault(); stamp.mutate(activeId!); }}>
            <div className="grid gap-1"><Label htmlFor="stamp-by">{t("sec.stampedBy")}</Label><Input id="stamp-by" value={by} onChange={event => setBy(event.target.value)} required /></div>
            <div className="grid gap-1"><Label htmlFor="stamp-model">{t("sec.model")}</Label><Input id="stamp-model" value={model} onChange={event => setModel(event.target.value)} /></div>
            <ActionError action={stamp} what={t("act.stampSection")} />
            <DialogFooter><Button type="button" variant="ghost" onClick={() => setStampOpen(false)}>{t("common.cancel")}</Button><Button type="submit" disabled={!by.trim() || stamp.isPending}>{t("sec.stampAction")}</Button></DialogFooter>
          </form></DialogContent>
      </Dialog>

      <Dialog open={packOpen} onOpenChange={setPackOpen}>
        <DialogContent><DialogHeader><DialogTitle>{t("sec.packTitle")}</DialogTitle><DialogDescription>{t("sec.packBody")}</DialogDescription></DialogHeader>
          <form className="grid gap-3" onSubmit={event => { event.preventDefault(); pack.mutate(undefined); }}>
            <div className="grid gap-1"><Label htmlFor="pack-target">{t("sec.target")}</Label><Input id="pack-target" value={target} onChange={event => setTarget(event.target.value)} required /></div>
            <ActionError action={pack} what={t("act.packContext")} />
            <DialogFooter><Button type="button" variant="ghost" onClick={() => setPackOpen(false)}>{t("common.cancel")}</Button><Button type="submit" disabled={!target.trim() || pack.isPending}>{t("sec.pack")}</Button></DialogFooter>
          </form></DialogContent>
      </Dialog>
    </div>}</QueryBoundary>;
}
