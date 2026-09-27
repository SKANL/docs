import { useEffect, useState } from "react";
import type { DocumentSection, ReviewApi } from "../api/models";
import { formatApiError } from "../api/client";

export function SectionEditor({ api, documentId }: { api: ReviewApi; documentId: string }) {
  const [sections, setSections] = useState<DocumentSection[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [body, setBody] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!documentId || !api.listDocumentSections) return;
    setMessage("");
    api.listDocumentSections(documentId).then(items => {
      setSections(items);
      const first = items[0];
      if (first) { setSelected(first.id); setBody(first.body); }
    }).catch(error => setMessage(formatApiError(error, "document sections")));
  }, [api, documentId]);

  if (!documentId || !api.listDocumentSections || !api.updateDocumentSection) return null;
  const updateSection = api.updateDocumentSection;
  const choose = (id: string) => { setSelected(id); setBody(sections.find(item => item.id === id)?.body ?? ""); setMessage(""); };
  const save = async () => {
    if (!selected) return;
    setBusy(true); setMessage("");
    try {
      await updateSection(selectedDocumentId(documentId), selected, body);
      setSections(items => items.map(item => item.id === selected ? { ...item, body } : item));
      setMessage("Section saved with revision provenance.");
    } catch (error) { setMessage(formatApiError(error, "section revision")); }
    finally { setBusy(false); }
  };
  return <section className="card" aria-labelledby="section-editor-title">
    <div className="card-title"><h2 id="section-editor-title">Section editor</h2><span className="muted">Authored content only; saves create a real revision.</span></div>
    <label htmlFor="section-select">Section</label>
    <select id="section-select" value={selected} onChange={event => choose(event.target.value)}>
      <option value="">Select a section</option>{sections.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}
    </select>
    <label htmlFor="section-body">Section body</label>
    <textarea id="section-body" value={body} onChange={event => setBody(event.target.value)} rows={12} disabled={!selected} />
    <button className="button" type="button" onClick={save} disabled={busy || !selected}>{busy ? "Saving…" : "Save section revision"}</button>
    {message && <p className="callout" role="status" aria-live="polite">{message}</p>}
  </section>;
}

function selectedDocumentId(documentId: string) { return documentId; }
