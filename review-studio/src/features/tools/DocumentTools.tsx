import { useState } from "react";
import { useApi } from "@/app/providers";
import { ErrorState } from "@/components/shared/ErrorState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ActionError, useAction } from "@/lib/actions";
import { useT } from "@/lib/i18n";
import { CheckOutcome } from "@/features/templates/Issues";
import type { FileTool } from "@/api/domains/tools";
import { StrictSwitch, ToolCard } from "./ToolCard";

type Props = { documentId: string };

/** collect-sources, collect-issues, collect-code-evidence, build-rules, build-ledger: each writes one workspace file. */
export function FileToolCard({ documentId, tool, title, description, withRepoRoot = false }: Props & { tool: FileTool; title: string; description: string; withRepoRoot?: boolean }) {
  const { t } = useT();
  const api = useApi();
  const [repoRoot, setRepoRoot] = useState("");
  const run = useAction(() => api.runFileTool!(tool, documentId, repoRoot.trim() ? { repoRoot: repoRoot.trim() } : {}), {
    success: result => result.degraded ? t("tl.couldNotRun", { title }) : t("tl.finished", { title }),
  });
  return <ToolCard title={title} description={description}>
    {withRepoRoot && <div className="grid max-w-md gap-1"><Label htmlFor={`${tool}-root`}>{t("tl.repoRoot")}</Label>
      <Input id={`${tool}-root`} autoComplete="off" value={repoRoot} onChange={event => setRepoRoot(event.target.value)} />
      <p className="text-xs text-muted-foreground">{t("tl.repoRootHint")}</p></div>}
    <Button type="button" className="w-fit" disabled={run.isPending} aria-label={t("tl.runLabel", { title })} onClick={() => run.mutate(undefined)}>{run.isPending ? t("tl.running") : t("tl.run")}</Button>
    <ActionError action={run} what={t("act.runTool", { title })} />
    {run.data && (run.data.degraded || !run.data.path
      ? <ErrorState title={t("tl.unavailable")} message={run.data.message ?? t("tl.noReason")} />
      : <p role="status" className="text-sm">{t("tl.wrote")} <code>{run.data.path}</code></p>)}
  </ToolCard>;
}

export function ReviewRulesCard({ documentId }: Props) {
  const { t } = useT();
  const api = useApi();
  const [strict, setStrict] = useState(false);
  const run = useAction(() => api.reviewRules!(documentId, { strict }), { success: result => result.passed ? t("tl.rules.passed") : t("tl.rules.found") });
  return <ToolCard title={t("tl.rules.title")} description={t("tl.rules.desc")}>
    <StrictSwitch id="review-rules-strict" checked={strict} onChange={setStrict} />
    <Button type="button" className="w-fit" disabled={run.isPending} aria-label={t("tl.runLabel", { title: t("tl.rules.title") })} onClick={() => run.mutate(undefined)}>{run.isPending ? t("tl.running") : t("tl.run")}</Button>
    <ActionError action={run} what={t("act.reviewRules")} />
    {run.data && <section role="status" aria-label={t("tl.result")} className="rounded-md border p-3"><CheckOutcome passed={run.data.passed} label={run.data.strict ? t("tl.strictWord") : undefined} issues={run.data.issues} /></section>}
  </ToolCard>;
}

export function BuildDocxCard({ documentId }: Props) {
  const { t } = useT();
  const api = useApi();
  const [output, setOutput] = useState("");
  const run = useAction(() => api.buildDocx!(documentId, output.trim() ? { output: output.trim() } : {}), { success: result => result.built ? t("tl.docx.built") : t("tl.docx.notBuilt") });
  return <ToolCard title={t("tl.docx.title")} description={t("tl.docx.desc")}>
    <div className="grid max-w-md gap-1"><Label htmlFor="docx-output">{t("tl.docx.output")}</Label><Input id="docx-output" autoComplete="off" placeholder="out/report.docx" value={output} onChange={event => setOutput(event.target.value)} />
      <p className="text-xs text-muted-foreground">{t("tl.docx.hint")}</p></div>
    <Button type="button" className="w-fit" disabled={run.isPending} aria-label={t("tl.runLabel", { title: t("tl.docx.title") })} onClick={() => run.mutate(undefined)}>{run.isPending ? t("tl.building") : t("tl.run")}</Button>
    <ActionError action={run} what={t("act.buildDocx")} />
    {run.data && (run.data.built && run.data.docx
      ? <p role="status" className="text-sm">{t("tl.docx.builtLine")} <code>{run.data.docx}</code></p>
      : <ErrorState title={t("tl.docx.failTitle")} message={run.data.message ?? t("tl.docx.failMsg")} />)}
  </ToolCard>;
}

/** DocxInspectionPanel: the audit outcome, its issues, and the server's Markdown report as text. */
export function DocxInspectionPanel({ documentId }: Props) {
  const { t } = useT();
  const api = useApi();
  const [strict, setStrict] = useState(false);
  const run = useAction(() => api.auditDocxFormat!(documentId, { strict }), { success: result => result.passed ? t("tl.audit.passed") : t("tl.audit.found") });
  return <ToolCard title={t("tl.audit.title")} description={t("tl.audit.desc")}>
    <StrictSwitch id="format-audit-strict" checked={strict} onChange={setStrict} />
    <Button type="button" className="w-fit" disabled={run.isPending} aria-label={t("tl.runLabel", { title: t("tl.audit.title") })} onClick={() => run.mutate(undefined)}>{run.isPending ? t("tl.auditing") : t("tl.run")}</Button>
    <ActionError action={run} what={t("act.auditDocx")} />
    {run.data && <>
      <section role="status" aria-label={t("tl.result")} className="rounded-md border p-3"><CheckOutcome passed={run.data.passed} label={run.data.docx} issues={run.data.issues} /></section>
      <section aria-label={t("tl.audit.report")} className="rounded-md border p-3"><pre className="text-xs whitespace-pre-wrap">{run.data.report}</pre></section>
    </>}
  </ToolCard>;
}
