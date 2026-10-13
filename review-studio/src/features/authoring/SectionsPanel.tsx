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
import { authoringKeys, useSections } from "./data";

function ReviewFindingsPanel({ result, onOpenSection }: { result: ReviewResult; onOpenSection(id: string): void }) {
  const where = (finding: ReviewFinding) => [finding.section && `section ${finding.section}`, finding.file, finding.page != null && `page ${finding.page}`].filter(Boolean).join(" · ");
  return <section aria-label="Review findings" className="grid gap-3 rounded-lg border bg-card p-4">
    <div className="flex items-center gap-2"><h3 className="font-semibold">Review findings</h3><Badge variant={result.passed ? "secondary" : "destructive"}>{result.passed ? "Passed" : "Needs attention"}</Badge>
      <span className="text-sm text-muted-foreground">{result.section_id ? `Section ${result.section_id}` : "Whole document"}</span></div>
    {result.findings.length === 0 ? <p className="text-sm text-muted-foreground">No findings.</p>
      : <ul className="grid gap-2">{result.findings.map((finding, index) => <li key={`${finding.code}-${index}`} className="grid gap-1 rounded-md border p-3 text-sm">
        <div className="flex flex-wrap items-center gap-2"><Badge variant={finding.severity === "low" ? "outline" : "destructive"}>{finding.severity}</Badge><code className="text-xs">{finding.code}</code><span className="text-muted-foreground">{finding.dimension}</span></div>
        <p>{finding.message}</p>
        {where(finding) && <p className="text-muted-foreground">{where(finding)}</p>}
        {finding.resolution_condition && <p className="text-muted-foreground">To resolve: {finding.resolution_condition}</p>}
        {finding.section && <Button type="button" variant="outline" size="sm" className="w-fit" aria-label={`Fix in section ${finding.section}`} onClick={() => onOpenSection(finding.section!)}>Fix in section</Button>}
      </li>)}</ul>}
  </section>;
}

export function SectionsPanel({ documentId }: { documentId: string }) {
  const api = useApi();
  const can = useCapability();
  const sections = useSections(documentId);
  // `?section=` lets a review finding open the section it points at.
  const [params] = useSearchParams();
  const [selected, setSelected] = useState<string | null>(params.get("section"));
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<{ id: string; focus: boolean } | null>(null);
  const [review, setReview] = useState<ReviewResult | null>(null);
  const [packed, setPacked] = useState<ContextPacked | null>(null);
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
  const draft = activeId ? drafts[activeId] : undefined;
  const body = draft ?? active?.body ?? "";
  const dirty = (id: string) => drafts[id] !== undefined && drafts[id] !== items.find(item => item.id === id)?.body;
  const anyDirty = items.some(item => dirty(item.id));

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
  const save = useAction(({ id, text }: { id: string; text: string }) => api.updateDocumentSection!(documentId, id, text), { success: (_result, { id }) => `Saved section ${id}.`, invalidate, onDone: (_result, { id }) => discard(id) });
  const build = useAction((id: string) => api.buildSection!(documentId, id), { success: result => `Built ${result.path}.`, invalidate });
  const reviewSection = useAction((id: string) => api.reviewSection!(documentId, id), { success: result => result.passed ? "Section review passed." : "Section review found issues.", onDone: setReview });
  const reviewDocument = useAction(() => api.reviewDocument!(documentId), { success: result => result.passed ? "Document review passed." : "Document review found issues.", onDone: setReview });
  const stamp = useAction((id: string) => api.stampSection!(documentId, id, { by: by.trim(), ...(model.trim() ? { model: model.trim() } : {}) }), { success: result => `Stamped ${result.section_id} as ${result.authored_by}.`, onDone: () => setStampOpen(false) });
  const pack = useAction(() => api.packContext!(documentId, target.trim()), { success: result => `Packed context for ${result.target}.`, onDone: result => { setPacked(result); setPackOpen(false); } });

  return <QueryBoundary query={sections} skeleton="h-48 w-full">{() => items.length === 0
    ? <EmptyState title="No sections yet" description="Add sources and build the document structure first. Sections appear here once they exist." />
    : <div className="grid gap-6">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-xl font-semibold">Sections</h2>
        <div className="flex flex-wrap gap-2">
          {can("review-document") && api.reviewDocument && <Button type="button" variant="outline" disabled={reviewDocument.isPending} onClick={() => reviewDocument.mutate(undefined)}>Review document</Button>}
          {can("pack-context") && api.packContext && <Button type="button" variant="outline" onClick={() => { pack.reset(); setPackOpen(true); }}>Pack context</Button>}
        </div></div>
      <ActionError action={reviewDocument} what="review the document" />
      <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
        <nav aria-label="Sections"><ul className="grid gap-1">{items.map(item => <li key={item.id}>
          <Button type="button" variant={item.id === activeId ? "secondary" : "ghost"} className="w-full justify-between" aria-current={item.id === activeId ? "true" : undefined} onClick={() => open(item.id)}>
            <span>{item.id}</span>{dirty(item.id) && <Badge variant="outline">unsaved</Badge>}</Button></li>)}</ul></nav>
        <div className="grid gap-3">
          <Label htmlFor="section-body">Section body</Label>
          <Textarea id="section-body" ref={editor} rows={14} value={body} onChange={event => activeId && setDrafts(current => ({ ...current, [activeId]: event.target.value }))} />
          <div className="flex flex-wrap gap-2">
            <Button type="button" disabled={!activeId || !dirty(activeId) || save.isPending} onClick={() => save.mutate({ id: activeId!, text: body })}>{save.isPending ? "Saving…" : "Save section"}</Button>
            {can("build-section") && api.buildSection && <Button type="button" variant="outline" disabled={build.isPending} onClick={() => build.mutate(activeId!)}>Build section</Button>}
            {can("review-section") && api.reviewSection && <Button type="button" variant="outline" disabled={reviewSection.isPending} onClick={() => reviewSection.mutate(activeId!)}>Review section</Button>}
            {can("stamp-section") && api.stampSection && <Button type="button" variant="outline" onClick={() => { stamp.reset(); setStampOpen(true); }}>Stamp section</Button>}
          </div>
          <ActionError action={save} what="save the section" />
          <ActionError action={build} what="build the section" />
          <ActionError action={reviewSection} what="review the section" />
        </div>
      </div>
      {packed && <section aria-label="Packed context" className="rounded-lg border bg-card p-4"><h3 className="font-semibold">Context packed for {packed.target}</h3><ul className="mt-2 list-disc pl-5 text-sm">{packed.paths.map(path => <li key={path}>{path}</li>)}</ul></section>}
      {review && <ReviewFindingsPanel result={review} onOpenSection={id => open(id, true)} />}

      <ConfirmActionDialog open={pending !== null} title="Discard unsaved changes?" description={`Your edits to ${activeId} have not been saved. Switching sections discards them.`} confirmLabel="Discard changes"
        onOpenChange={next => { if (!next) setPending(null); }} onConfirm={() => { if (pending && activeId) { discard(activeId); apply(pending.id, pending.focus); } setPending(null); }} />

      <Dialog open={stampOpen} onOpenChange={setStampOpen}>
        <DialogContent><DialogHeader><DialogTitle>Stamp section {activeId}</DialogTitle><DialogDescription>Records who authored this section and with which model.</DialogDescription></DialogHeader>
          <form className="grid gap-3" onSubmit={event => { event.preventDefault(); stamp.mutate(activeId!); }}>
            <div className="grid gap-1"><Label htmlFor="stamp-by">Stamped by</Label><Input id="stamp-by" value={by} onChange={event => setBy(event.target.value)} required /></div>
            <div className="grid gap-1"><Label htmlFor="stamp-model">Model</Label><Input id="stamp-model" value={model} onChange={event => setModel(event.target.value)} /></div>
            <ActionError action={stamp} what="stamp the section" />
            <DialogFooter><Button type="button" variant="ghost" onClick={() => setStampOpen(false)}>Cancel</Button><Button type="submit" disabled={!by.trim() || stamp.isPending}>Stamp</Button></DialogFooter>
          </form></DialogContent>
      </Dialog>

      <Dialog open={packOpen} onOpenChange={setPackOpen}>
        <DialogContent><DialogHeader><DialogTitle>Pack context</DialogTitle><DialogDescription>Use a section id, &quot;all&quot; for every section, or &quot;document&quot; for the whole document.</DialogDescription></DialogHeader>
          <form className="grid gap-3" onSubmit={event => { event.preventDefault(); pack.mutate(undefined); }}>
            <div className="grid gap-1"><Label htmlFor="pack-target">Target</Label><Input id="pack-target" value={target} onChange={event => setTarget(event.target.value)} required /></div>
            <ActionError action={pack} what="pack the context" />
            <DialogFooter><Button type="button" variant="ghost" onClick={() => setPackOpen(false)}>Cancel</Button><Button type="submit" disabled={!target.trim() || pack.isPending}>Pack</Button></DialogFooter>
          </form></DialogContent>
      </Dialog>
    </div>}</QueryBoundary>;
}
