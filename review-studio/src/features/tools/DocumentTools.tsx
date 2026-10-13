import { useState } from "react";
import { useApi } from "@/app/providers";
import { ErrorState } from "@/components/shared/ErrorState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ActionError, useAction } from "@/features/authoring/data";
import { CheckOutcome } from "@/features/templates/Issues";
import type { FileTool } from "@/api/domains/tools";
import { StrictSwitch, ToolCard } from "./ToolCard";

type Props = { documentId: string };

/** collect-sources, collect-issues, collect-code-evidence, build-rules, build-ledger: each writes one workspace file. */
export function FileToolCard({ documentId, tool, title, description, withRepoRoot = false }: Props & { tool: FileTool; title: string; description: string; withRepoRoot?: boolean }) {
  const api = useApi();
  const [repoRoot, setRepoRoot] = useState("");
  const run = useAction(() => api.runFileTool!(tool, documentId, repoRoot.trim() ? { repoRoot: repoRoot.trim() } : {}), {
    success: result => result.degraded ? `${title} could not run.` : `${title} finished.`,
  });
  return <ToolCard title={title} description={description}>
    {withRepoRoot && <div className="grid max-w-md gap-1"><Label htmlFor={`${tool}-root`}>Repository root (optional)</Label>
      <Input id={`${tool}-root`} autoComplete="off" value={repoRoot} onChange={event => setRepoRoot(event.target.value)} />
      <p className="text-xs text-muted-foreground">Only the workspace or the document&apos;s configured evidence root is accepted; the server refuses anything else.</p></div>}
    <Button type="button" className="w-fit" disabled={run.isPending} aria-label={`Run ${title}`} onClick={() => run.mutate(undefined)}>{run.isPending ? "Running…" : "Run"}</Button>
    <ActionError action={run} what={`run ${title}`} />
    {run.data && (run.data.degraded || !run.data.path
      ? <ErrorState title="Tool unavailable" message={run.data.message ?? "The tool could not run and reported no reason."} />
      : <p role="status" className="text-sm">Wrote <code>{run.data.path}</code></p>)}
  </ToolCard>;
}

export function ReviewRulesCard({ documentId }: Props) {
  const api = useApi();
  const [strict, setStrict] = useState(false);
  const run = useAction(() => api.reviewRules!(documentId, { strict }), { success: result => result.passed ? "Rules review passed." : "Rules review found issues." });
  return <ToolCard title="Review rules" description="Check the evidence rules for the current document.">
    <StrictSwitch id="review-rules-strict" checked={strict} onChange={setStrict} />
    <Button type="button" className="w-fit" disabled={run.isPending} aria-label="Run Review rules" onClick={() => run.mutate(undefined)}>{run.isPending ? "Running…" : "Run"}</Button>
    <ActionError action={run} what="review the rules" />
    {run.data && <section role="status" aria-label="Result" className="rounded-md border p-3"><CheckOutcome passed={run.data.passed} label={run.data.strict ? "strict" : undefined} issues={run.data.issues} /></section>}
  </ToolCard>;
}

export function BuildDocxCard({ documentId }: Props) {
  const api = useApi();
  const [output, setOutput] = useState("");
  const run = useAction(() => api.buildDocx!(documentId, output.trim() ? { output: output.trim() } : {}), { success: result => result.built ? "DOCX built." : "DOCX was not built." });
  return <ToolCard title="Build DOCX" description="Assemble the document into a Word file with pandoc.">
    <div className="grid max-w-md gap-1"><Label htmlFor="docx-output">Output path (optional)</Label><Input id="docx-output" autoComplete="off" placeholder="out/report.docx" value={output} onChange={event => setOutput(event.target.value)} />
      <p className="text-xs text-muted-foreground">A relative .docx path inside the workspace. Leave empty for the draft folder.</p></div>
    <Button type="button" className="w-fit" disabled={run.isPending} aria-label="Run Build DOCX" onClick={() => run.mutate(undefined)}>{run.isPending ? "Building…" : "Run"}</Button>
    <ActionError action={run} what="build the DOCX" />
    {run.data && (run.data.built && run.data.docx
      ? <p role="status" className="text-sm">Built <code>{run.data.docx}</code></p>
      : <ErrorState title="DOCX not built" message={run.data.message ?? "The server did not build a DOCX and gave no reason."} />)}
  </ToolCard>;
}

/** DocxInspectionPanel: the audit outcome, its issues, and the server's Markdown report as text. */
export function DocxInspectionPanel({ documentId }: Props) {
  const api = useApi();
  const [strict, setStrict] = useState(false);
  const run = useAction(() => api.auditDocxFormat!(documentId, { strict }), { success: result => result.passed ? "Format audit passed." : "Format audit found issues." });
  return <ToolCard title="Format audit DOCX" description="Audit the built Word file against the document's format rules.">
    <StrictSwitch id="format-audit-strict" checked={strict} onChange={setStrict} />
    <Button type="button" className="w-fit" disabled={run.isPending} aria-label="Run Format audit DOCX" onClick={() => run.mutate(undefined)}>{run.isPending ? "Auditing…" : "Run"}</Button>
    <ActionError action={run} what="audit the DOCX" />
    {run.data && <>
      <section role="status" aria-label="Result" className="rounded-md border p-3"><CheckOutcome passed={run.data.passed} label={run.data.docx} issues={run.data.issues} /></section>
      <section aria-label="Audit report" className="rounded-md border p-3"><pre className="text-xs whitespace-pre-wrap">{run.data.report}</pre></section>
    </>}
  </ToolCard>;
}
