import { useEffect, useState, type FormEvent } from "react";
import type { Template } from "@/api/models";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type Props = { open: boolean; pending: boolean; templates: Template[]; error?: string; onOpenChange(open: boolean): void; onSubmit(input: { documentId: string; title: string; template: string }): void };

export function DocumentCreateDialog({ open, pending, templates, error, onOpenChange, onSubmit }: Props) {
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
      <DialogHeader><DialogTitle>Create document</DialogTitle><DialogDescription id="document-create-description">Choose an identifier and a template. The service initializes the document in the selected workspace.</DialogDescription></DialogHeader>
      {pending && <p className="text-sm text-muted-foreground" role="status">This request cannot be cancelled after it is sent. You may close this dialog; the action will finish and controls stay unavailable until then.</p>}
      <form onSubmit={submit} className="grid gap-4">
        <div className="grid gap-2"><Label htmlFor="document-id">Document ID</Label><Input id="document-id" name="document_id" autoComplete="off" required value={documentId} onChange={event => setDocumentId(event.target.value)} /></div>
        <div className="grid gap-2"><Label htmlFor="document-title">Title</Label><Input id="document-title" name="title" required value={title} onChange={event => setTitle(event.target.value)} /></div>
        <div className="grid gap-2"><Label htmlFor="document-template">Template</Label>
          <Select value={template} onValueChange={setTemplate} disabled={!templates.length}>
            <SelectTrigger id="document-template" aria-label="Template" className="w-full"><SelectValue placeholder="Choose a template" /></SelectTrigger>
            <SelectContent>{templates.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        {!templates.length && <p className="text-sm text-destructive" role="alert">No templates are available in this workspace.</p>}
        {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Close</Button>
          <Button type="submit" disabled={pending || !template || !documentId.trim() || !title.trim()}>{pending ? "Creating…" : "Create document"}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
