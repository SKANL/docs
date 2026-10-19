import { useState } from "react";
import { useApi } from "@/app/providers";
import { useMode } from "@/app/mode";
import { useT } from "@/lib/i18n";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { SourceIngestResult } from "@/api/domains/authoring";
import { ActionError, useAction } from "@/lib/actions";
import { ErrorState } from "@/components/shared/ErrorState";
import { Unavailable } from "@/components/shared/Unavailable";
import { fileToBase64 } from "@/lib/files";
import { useCapability } from "@/lib/capability-registry";
import { authoringKeys } from "./data";

function IngestResult({ result }: { result: SourceIngestResult }) {
  const { t } = useT();
  return <section aria-label={t("src.ingestResult")} className="grid gap-4">
    <div className="flex items-center gap-2"><h3 className="text-lg font-semibold">{t("src.ingestResult")}</h3><Badge variant={result.succeeded ? "secondary" : "destructive"}>{result.succeeded ? t("src.succeeded") : t("status.failed")}</Badge></div>
    {!result.succeeded && <Alert variant="destructive"><AlertTitle>{t("src.didNotComplete")}</AlertTitle><AlertDescription>{t("src.didNotCompleteBody")}</AlertDescription></Alert>}
    {result.uploaded.length > 0 && <Table>
      <TableHeader><TableRow><TableHead>{t("src.uploadedFile")}</TableHead><TableHead>{t("src.size")}</TableHead><TableHead>{t("src.duplicate")}</TableHead></TableRow></TableHeader>
      <TableBody>{result.uploaded.map(file => <TableRow key={file.sha256 + file.filename}><TableCell>{file.filename}</TableCell><TableCell>{t("src.bytes", { size: file.size })}</TableCell><TableCell>{file.deduplicated ? t("src.alreadyIngested") : t("src.new")}</TableCell></TableRow>)}</TableBody>
    </Table>}
    <div className="grid gap-3 sm:grid-cols-2">
      {result.stages.map(stage => <Card key={stage.name}>
        <CardHeader><CardTitle className="flex items-center gap-2 text-base"><span>{stage.name}</span><Badge variant={stage.succeeded ? "secondary" : "destructive"}>{stage.succeeded ? t("src.stageOk") : t("src.stageFailed")}</Badge></CardTitle>
          <CardDescription>{[stage.status, stage.processed !== null && t("src.processed", { count: stage.processed }), stage.files.length > 0 && t("src.fileCount", { count: stage.files.length })].filter(Boolean).join(" · ") || t("src.noDetails")}</CardDescription></CardHeader>
        <CardContent className="grid gap-2 text-sm">
          {stage.errors.length > 0 && <ul aria-label={t("src.errorsIn", { name: stage.name })} className="list-disc pl-5 text-destructive">{stage.errors.map(text => <li key={text}>{text}</li>)}</ul>}
          {stage.warnings.length > 0 && <ul aria-label={t("src.warningsIn", { name: stage.name })} className="list-disc pl-5 text-muted-foreground">{stage.warnings.map(text => <li key={text}>{text}</li>)}</ul>}
        </CardContent>
      </Card>)}
    </div>
  </section>;
}

export function SourcesPanel({ documentId }: { documentId: string }) {
  const api = useApi();
  const can = useCapability();
  const { advanced } = useMode();
  const { t } = useT();
  const [files, setFiles] = useState<File[]>([]);
  const ingest = useAction(
    async () => api.ingestSources!(documentId, await Promise.all(files.map(async file => ({ filename: file.name, content_base64: await fileToBase64(file) })))),
    { success: result => result.succeeded ? t("src.ingested") : t("src.ingestFailures"), invalidate: [authoringKeys.classification(documentId), authoringKeys.sections(documentId)] },
  );
  // Stores each file as a hash-named copy without converting it; the same upload, a different verb.
  // Files are stored one by one: a failure must not hide the ones already stored, so nothing here rejects.
  const imported = useAction(
    async () => {
      const outcomes = await Promise.allSettled(files.map(async file => api.importSourceFile!(documentId, { filename: file.name, content_base64: await fileToBase64(file) })));
      return {
        stored: outcomes.flatMap(outcome => outcome.status === "fulfilled" ? [outcome.value] : []),
        failed: outcomes.flatMap((outcome, index) => outcome.status === "rejected" ? [{ name: files[index]!.name, reason: outcome.reason as unknown }] : []),
      };
    },
    { success: ({ stored }) => stored.length ? t("src.importedList", { files: stored.map(result => result.filename).join(", ") }) : "", invalidate: [authoringKeys.classification(documentId)], onDone: () => { setFiles([]); setInputKey(key => key + 1); } },
  );
  // A fresh key remounts the input: clearing state alone would leave the old selection showing in the form.
  const [inputKey, setInputKey] = useState(0);
  const canIngest = can("source.ingest") && !!api.ingestSources;
  const canImport = advanced && can("document.import") && !!api.importSourceFile;
  return <div className="grid gap-6">
    <h2 className="text-xl font-semibold">{t("au.tab.sources")}</h2>
    {canIngest || canImport ? <form className="grid max-w-xl gap-3" onSubmit={event => { event.preventDefault(); if (canIngest) ingest.mutate(undefined); }}>
      <Label htmlFor="source-files">{t("src.files")}</Label>
      <Input key={inputKey} id="source-files" type="file" multiple onChange={event => setFiles(Array.from(event.target.files ?? []))} />
      {canIngest && <p className="text-sm text-muted-foreground">{t("src.hint")}</p>}
      <div className="flex flex-wrap gap-2">
        {canIngest && <Button type="submit" disabled={ingest.isPending}>{ingest.isPending ? t("src.ingesting") : t("src.ingest")}</Button>}
        {canImport && <Button type="button" variant="outline" disabled={files.length === 0 || imported.isPending} onClick={() => imported.mutate(undefined)}>{imported.isPending ? t("src.importing") : t("sources.importOnly")}</Button>}
      </div>
    </form> : <Unavailable>{t("src.unavailable")}</Unavailable>}
    <ActionError action={ingest} what={t("act.ingestSources")} />
    {ingest.data && <IngestResult result={ingest.data} />}
    {imported.data && imported.data.failed.length > 0 && <ErrorState title={t("sources.importFailed", { files: imported.data.failed.map(item => item.name).join(", ") })} error={imported.data.failed[0]!.reason} />}
    {imported.data && imported.data.stored.length > 0 && <ul role="status" className="grid gap-1 text-sm">{imported.data.stored.map(result => <li key={result.path}>{result.deduplicated ? t("src.alreadyImported") : t("src.imported")}<code>{result.path}</code> ({t("src.bytes", { size: result.size })})</li>)}</ul>}
  </div>;
}
