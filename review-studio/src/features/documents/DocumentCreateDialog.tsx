import { useEffect, useState, type FormEvent } from "react";
import type { Template } from "@/api/models";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ErrorState } from "@/components/shared/ErrorState";
import { Label } from "@/components/ui/label";
import { useT } from "@/lib/i18n";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type Props = { open: boolean; pending: boolean; templates: Template[]; error?: unknown; onOpenChange(open: boolean): void; onSubmit(input: { documentId: string; title: string; template: string }): void };

export function DocumentCreateDialog({ open, pending, templates, error, onOpenChange, onSubmit }: Props) {
  const { t } = useT();
  const [documentId, setDocumentId] = useState("");
  const [title, setTitle] = useState("");
  const [template, setTemplate] = useState("");
  useEffect(() => { if (open) { setDocumentId(""); setTitle(""); setTemplate(templates[0]?.id ?? ""); } }, [open, templates]);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (template) onSubmit({ documentId: documentId.trim(), title: title.trim(), template });
  }
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent showCloseButton={false} aria-describedby="document-create-description">
      <DialogHeader><DialogTitle>{t("doc.create")}</DialogTitle><DialogDescription id="document-create-description">{t("doc.createBody")}</DialogDescription></DialogHeader>
      {pending && <p className="text-sm text-muted-foreground" role="status">{t("common.pendingNote")}</p>}
      <form onSubmit={submit} className="grid gap-4">
        <div className="grid gap-2"><Label htmlFor="document-id">{t("doc.id")}</Label><Input id="document-id" name="document_id" autoComplete="off" required value={documentId} onChange={event => setDocumentId(event.target.value)} /></div>
        <div className="grid gap-2"><Label htmlFor="document-title">{t("doc.title")}</Label><Input id="document-title" name="title" required value={title} onChange={event => setTitle(event.target.value)} /></div>
        <div className="grid gap-2"><Label htmlFor="document-template">{t("doc.template")}</Label>
          <Select value={template} onValueChange={setTemplate} disabled={!templates.length}>
            <SelectTrigger id="document-template" aria-label={t("doc.template")} className="w-full"><SelectValue placeholder={t("doc.chooseTemplate")} /></SelectTrigger>
            <SelectContent>{templates.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        {!templates.length && <p className="text-sm text-destructive" role="alert">{t("doc.noTemplates")}</p>}
        {error != null && <ErrorState error={error} />}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>{t("common.close")}</Button>
          <Button type="submit" disabled={pending || !template || !documentId.trim() || !title.trim()}>{pending ? t("common.creating") : t("doc.create")}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
