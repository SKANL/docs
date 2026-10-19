import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import { ApiError } from "@/api/errors";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { ErrorState } from "@/components/shared/ErrorState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ActionError } from "@/lib/actions";
import { useT } from "@/lib/i18n";
import { fileToBase64 } from "@/lib/files";
import { Facts, scalarRows } from "@/components/shared/Facts";
import type { TranslateInput, TranslateResult } from "@/api/domains/tools";
import { ToolCard } from "./ToolCard";

function Outcome({ result, onDownload }: { result: TranslateResult; onDownload?: () => void }) {
  const { t } = useT();
  if (result.status !== "translated") return <ErrorState title={t(`tl.tr.status.${result.status}`)} message={result.message ?? t("tl.tr.noReason")} />;
  return <section role="status" aria-label={t("tl.tr.result")} className="grid gap-2 rounded-md border p-3">
    <div className="flex items-center gap-2"><Badge variant="secondary">{t("tl.tr.status.translated")}</Badge>{result.line && <span className="text-sm">{result.line}</span>}</div>
    <Facts rows={[[t("tl.tr.source"), result.source ?? undefined], [t("tl.tr.output"), result.output ?? undefined], [t("tl.tr.pending"), result.pending ?? undefined], ...(result.report ? scalarRows(result.report) : [])]} />
    {onDownload && <Button type="button" variant="outline" size="sm" className="w-fit" onClick={onDownload}>{t("tl.tr.download")}</Button>}
  </section>;
}

/** PDF translation from a workspace artifact or an upload. An existing output is replaced only after an explicit confirmation. */
export function TranslationWorkflow() {
  const { t } = useT();
  const api = useApi();
  const [source, setSource] = useState<"artifact" | "upload">("artifact");
  const [artifactId, setArtifactId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [to, setTo] = useState("");
  const [sourceLang, setSourceLang] = useState("auto");
  const artifacts = useQuery({ queryKey: ["tools", "pdf-artifacts"], queryFn: async () => (await api.listArtifacts()).filter(item => item.name.toLowerCase().endsWith(".pdf")) });
  const run = useMutation({ mutationFn: (input: TranslateInput) => api.translatePdf!(input) });

  const save = useMutation({ mutationFn: async (path: string) => {
    const url = URL.createObjectURL(await api.downloadTranslation!(path));
    try {
      const link = document.createElement("a");
      link.href = url;
      link.download = path.split("/").pop() ?? "translation.pdf";
      link.click();
    } finally { URL.revokeObjectURL(url); }
  } });
  const download = (path: string) => save.mutate(path);

  async function submit(overwrite: boolean) {
    const base = { to: to.trim(), sourceLang: sourceLang.trim() || "auto", overwrite };
    run.mutate(source === "artifact" ? { artifactId, ...base } : { filename: file!.name, contentBase64: await fileToBase64(file!), ...base });
  }
  const exists = run.error instanceof ApiError && run.error.code === "output_exists" && !run.variables?.overwrite;
  const ready = !!to.trim() && (source === "artifact" ? !!artifactId : !!file);

  return <ToolCard title={t("tl.tr.title")} description={t("tl.tr.desc")}>
    <form className="grid max-w-xl gap-3" onSubmit={event => { event.preventDefault(); if (ready) void submit(false); }}>
      <fieldset className="flex flex-wrap gap-4"><legend className="sr-only">{t("tl.tr.source")}</legend>
        <label className="flex items-center gap-2 text-sm"><input type="radio" name="translate-source" checked={source === "artifact"} onChange={() => setSource("artifact")} />{t("tl.tr.fromArtifact")}</label>
        <label className="flex items-center gap-2 text-sm"><input type="radio" name="translate-source" checked={source === "upload"} onChange={() => setSource("upload")} />{t("tl.tr.fromUpload")}</label>
      </fieldset>
      {source === "artifact"
        ? <div className="grid gap-1"><Label htmlFor="translate-artifact">{t("tl.tr.pdfArtifact")}</Label>
          <Select value={artifactId} onValueChange={setArtifactId}>
            <SelectTrigger id="translate-artifact" aria-label={t("tl.tr.pdfArtifact")} className="w-full"><SelectValue placeholder={artifacts.data?.length === 0 ? t("tl.tr.noPdfs") : t("tl.tr.choose")} /></SelectTrigger>
            <SelectContent>{(artifacts.data ?? []).map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent>
          </Select></div>
        : <div className="grid gap-1"><Label htmlFor="translate-file">{t("tl.tr.file")}</Label><Input id="translate-file" type="file" accept=".pdf,application/pdf" onChange={event => setFile(event.target.files?.[0] ?? null)} /></div>}
      <div className="flex flex-wrap gap-4">
        <div className="grid gap-1"><Label htmlFor="translate-to">{t("tl.tr.target")}</Label><Input id="translate-to" className="w-36" autoComplete="off" placeholder="es" value={to} onChange={event => setTo(event.target.value)} /></div>
        <div className="grid gap-1"><Label htmlFor="translate-from">{t("tl.tr.sourceLang")}</Label><Input id="translate-from" className="w-36" autoComplete="off" value={sourceLang} onChange={event => setSourceLang(event.target.value)} /></div>
      </div>
      <Button type="submit" className="w-fit" disabled={!ready || run.isPending} aria-label={t("tl.runLabel", { title: t("tl.tr.title") })}>{run.isPending ? t("tl.translating") : t("tl.run")}</Button>
    </form>
    {!exists && <ActionError action={run} what={t("act.translate")} />}
    <ActionError action={save} what={t("act.downloadTranslation")} />
    {run.data && <Outcome result={run.data} onDownload={run.data.output && api.downloadTranslation ? () => void download(run.data!.output!) : undefined} />}
    <ConfirmActionDialog open={exists} title={t("tl.tr.replaceTitle")} description={t("tl.tr.replaceBody")}
      confirmLabel={t("tl.tr.replaceConfirm")} pending={run.isPending} onOpenChange={open => { if (!open) run.reset(); }}
      onConfirm={() => { if (run.variables) run.mutate({ ...run.variables, overwrite: true }); }} />
  </ToolCard>;
}
