import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import { ApiError } from "@/api/client";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { ErrorState } from "@/components/shared/ErrorState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ActionError, fileToBase64 } from "@/features/authoring/data";
import { Facts, scalarRows } from "@/features/quality/data";
import type { TranslateInput, TranslateResult } from "@/api/domains/tools";
import { ToolCard } from "./ToolCard";

const label: Record<TranslateResult["status"], string> = { translated: "Translated", unavailable: "Unavailable", untranslatable: "Untranslatable" };

function Outcome({ result }: { result: TranslateResult }) {
  if (result.status !== "translated") return <ErrorState title={label[result.status]} message={result.message ?? "The server gave no reason."} />;
  return <section role="status" aria-label="Translation result" className="grid gap-2 rounded-md border p-3">
    <div className="flex items-center gap-2"><Badge variant="secondary">{label.translated}</Badge>{result.line && <span className="text-sm">{result.line}</span>}</div>
    <Facts rows={[["Source", result.source ?? undefined], ["Translated PDF", result.output ?? undefined], ["Pending blocks (provenance)", result.pending ?? undefined], ...(result.report ? scalarRows(result.report) : [])]} />
  </section>;
}

/** PDF translation from a workspace artifact or an upload. An existing output is replaced only after an explicit confirmation. */
export function TranslationWorkflow() {
  const api = useApi();
  const [source, setSource] = useState<"artifact" | "upload">("artifact");
  const [artifactId, setArtifactId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [to, setTo] = useState("");
  const [sourceLang, setSourceLang] = useState("auto");
  const artifacts = useQuery({ queryKey: ["tools", "pdf-artifacts"], queryFn: async () => (await api.listArtifacts()).filter(item => item.name.toLowerCase().endsWith(".pdf")) });
  const run = useMutation({ mutationFn: (input: TranslateInput) => api.translatePdf!(input) });

  async function submit(overwrite: boolean) {
    const base = { to: to.trim(), sourceLang: sourceLang.trim() || "auto", overwrite };
    run.mutate(source === "artifact" ? { artifactId, ...base } : { filename: file!.name, contentBase64: await fileToBase64(file!), ...base });
  }
  const exists = run.error instanceof ApiError && run.error.code === "output_exists" && !run.variables?.overwrite;
  const ready = !!to.trim() && (source === "artifact" ? !!artifactId : !!file);

  return <ToolCard title="Translate PDF" description="Translate a PDF into another language, keeping its layout.">
    <form className="grid max-w-xl gap-3" onSubmit={event => { event.preventDefault(); if (ready) void submit(false); }}>
      <fieldset className="flex flex-wrap gap-4"><legend className="sr-only">Source</legend>
        <label className="flex items-center gap-2 text-sm"><input type="radio" name="translate-source" checked={source === "artifact"} onChange={() => setSource("artifact")} />Workspace artifact</label>
        <label className="flex items-center gap-2 text-sm"><input type="radio" name="translate-source" checked={source === "upload"} onChange={() => setSource("upload")} />Upload a PDF</label>
      </fieldset>
      {source === "artifact"
        ? <div className="grid gap-1"><Label htmlFor="translate-artifact">PDF artifact</Label>
          <Select value={artifactId} onValueChange={setArtifactId}>
            <SelectTrigger id="translate-artifact" aria-label="PDF artifact" className="w-full"><SelectValue placeholder={artifacts.data?.length === 0 ? "No PDF artifacts" : "Choose a PDF"} /></SelectTrigger>
            <SelectContent>{(artifacts.data ?? []).map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent>
          </Select></div>
        : <div className="grid gap-1"><Label htmlFor="translate-file">PDF file</Label><Input id="translate-file" type="file" accept=".pdf,application/pdf" onChange={event => setFile(event.target.files?.[0] ?? null)} /></div>}
      <div className="flex flex-wrap gap-4">
        <div className="grid gap-1"><Label htmlFor="translate-to">Target language</Label><Input id="translate-to" className="w-36" autoComplete="off" placeholder="es" value={to} onChange={event => setTo(event.target.value)} /></div>
        <div className="grid gap-1"><Label htmlFor="translate-from">Source language</Label><Input id="translate-from" className="w-36" autoComplete="off" value={sourceLang} onChange={event => setSourceLang(event.target.value)} /></div>
      </div>
      <Button type="submit" className="w-fit" disabled={!ready || run.isPending} aria-label="Run Translate PDF">{run.isPending ? "Translating…" : "Run"}</Button>
    </form>
    {!exists && <ActionError action={run} what="translate the PDF" />}
    {run.data && <Outcome result={run.data} />}
    <ConfirmActionDialog open={exists} title="Replace the existing translation?" description="A translation with this name already exists. Running again overwrites that file."
      confirmLabel="Replace translation" pending={run.isPending} onOpenChange={open => { if (!open) run.reset(); }}
      onConfirm={() => { if (run.variables) run.mutate({ ...run.variables, overwrite: true }); }} />
  </ToolCard>;
}
