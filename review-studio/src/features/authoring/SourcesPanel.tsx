import { useState } from "react";
import { useApi } from "@/app/providers";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { SourceIngestResult } from "@/api/domains/authoring";
import { ActionError, Unavailable, authoringKeys, fileToBase64, useAction, useCapability } from "./data";

function IngestResult({ result }: { result: SourceIngestResult }) {
  return <section aria-label="Ingest result" className="grid gap-4">
    <div className="flex items-center gap-2"><h3 className="text-lg font-semibold">Ingest result</h3><Badge variant={result.succeeded ? "secondary" : "destructive"}>{result.succeeded ? "Succeeded" : "Failed"}</Badge></div>
    {!result.succeeded && <Alert variant="destructive"><AlertTitle>Ingestion did not complete</AlertTitle><AlertDescription>Fix or replace the failing source named below, then ingest again. Sources that already converted are kept.</AlertDescription></Alert>}
    {result.uploaded.length > 0 && <Table>
      <TableHeader><TableRow><TableHead>Uploaded file</TableHead><TableHead>Size</TableHead><TableHead>Duplicate</TableHead></TableRow></TableHeader>
      <TableBody>{result.uploaded.map(file => <TableRow key={file.sha256 + file.filename}><TableCell>{file.filename}</TableCell><TableCell>{file.size} bytes</TableCell><TableCell>{file.deduplicated ? "Already ingested" : "New"}</TableCell></TableRow>)}</TableBody>
    </Table>}
    <div className="grid gap-3 sm:grid-cols-2">
      {result.stages.map(stage => <Card key={stage.name}>
        <CardHeader><CardTitle className="flex items-center gap-2 text-base"><span>{stage.name}</span><Badge variant={stage.succeeded ? "secondary" : "destructive"}>{stage.succeeded ? "ok" : "failed"}</Badge></CardTitle>
          <CardDescription>{[stage.status, stage.processed !== null && `${stage.processed} processed`, stage.files.length > 0 && `${stage.files.length} files`].filter(Boolean).join(" · ") || "No details reported"}</CardDescription></CardHeader>
        <CardContent className="grid gap-2 text-sm">
          {stage.errors.length > 0 && <ul aria-label={`Errors in ${stage.name}`} className="list-disc pl-5 text-destructive">{stage.errors.map(text => <li key={text}>{text}</li>)}</ul>}
          {stage.warnings.length > 0 && <ul aria-label={`Warnings in ${stage.name}`} className="list-disc pl-5 text-muted-foreground">{stage.warnings.map(text => <li key={text}>{text}</li>)}</ul>}
        </CardContent>
      </Card>)}
    </div>
  </section>;
}

function ImportSource({ documentId }: { documentId: string }) {
  const api = useApi();
  const [file, setFile] = useState<File | null>(null);
  const imported = useAction(async () => api.importSourceFile!(documentId, { filename: file!.name, content_base64: await fileToBase64(file!) }), {
    success: result => `Imported ${result.filename}.`, invalidate: [authoringKeys.classification(documentId)], onDone: () => setFile(null),
  });
  return <section aria-label="Import source file" className="grid max-w-xl gap-3">
    <h3 className="text-lg font-semibold">Import source file</h3>
    <p className="text-sm text-muted-foreground">Stores one file with the document as a hash-named copy, without converting it. Importing the same file again changes nothing.</p>
    <form className="grid gap-3" onSubmit={event => { event.preventDefault(); if (file) imported.mutate(undefined); }}>
      <Label htmlFor="import-file">Source file</Label>
      <Input id="import-file" type="file" onChange={event => setFile(event.target.files?.[0] ?? null)} />
      <Button type="submit" variant="outline" className="w-fit" disabled={!file || imported.isPending}>{imported.isPending ? "Importing…" : "Import source file"}</Button>
    </form>
    <ActionError action={imported} what="import the file" />
    {imported.data && <p role="status" className="text-sm">{imported.data.deduplicated ? "Already imported: " : "Imported: "}<code>{imported.data.path}</code> ({imported.data.size} bytes)</p>}
  </section>;
}

export function SourcesPanel({ documentId }: { documentId: string }) {
  const api = useApi();
  const can = useCapability();
  const [files, setFiles] = useState<File[]>([]);
  const ingest = useAction(
    async () => api.ingestSources!(documentId, await Promise.all(files.map(async file => ({ filename: file.name, content_base64: await fileToBase64(file) })))),
    { success: result => result.succeeded ? "Sources ingested." : "Ingestion finished with failures.", invalidate: [authoringKeys.classification(documentId), authoringKeys.sections(documentId)] },
  );
  return <div className="grid gap-6">
    <h2 className="text-xl font-semibold">Sources</h2>
    {can("source.ingest") && api.ingestSources ? <form className="grid max-w-xl gap-3" onSubmit={event => { event.preventDefault(); ingest.mutate(undefined); }}>
      <Label htmlFor="source-files">Source files</Label>
      <Input id="source-files" type="file" multiple onChange={event => setFiles(Array.from(event.target.files ?? []))} />
      <p className="text-sm text-muted-foreground">Upload new files, or leave empty to ingest what is already in the inbox.</p>
      <Button type="submit" className="w-fit" disabled={ingest.isPending}>{ingest.isPending ? "Ingesting…" : "Ingest sources"}</Button>
    </form> : <Unavailable>Source ingestion is not available on this server.</Unavailable>}
    <ActionError action={ingest} what="ingest sources" />
    {ingest.data && <IngestResult result={ingest.data} />}
    {can("document.import") && api.importSourceFile && <ImportSource documentId={documentId} />}
  </div>;
}
