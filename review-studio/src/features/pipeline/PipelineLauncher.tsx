import { focusTargets } from "@/lib/focus-targets";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ActionError, useAction } from "@/lib/actions";
import { useMode } from "@/app/mode";
import { useT } from "@/lib/i18n";
import { useCapability } from "@/lib/capability-registry";
import { type ActiveContext } from "@/app/active-context";
import type { OutputFormat, RunPolicy } from "@/api/domains/pipeline";

const formats: OutputFormat[] = ["docx", "pdf", "html"];
const policies: RunPolicy[] = ["draft", "strict", "release"];
const stageActions = [["prepare", "document.prepare"], ["build", "document.build"], ["verify", "document.verify"]] as const;

function Choice({ id, label, value, options, optionLabel = option => option, onChange }: { id: string; label: string; value: string; options: readonly string[]; optionLabel?(option: string): string; onChange(value: string): void }) {
  return <div className="grid gap-1">
    <Label htmlFor={id}>{label}</Label>
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id} aria-label={label} className="w-36"><SelectValue /></SelectTrigger>
      <SelectContent>{options.map(option => <SelectItem key={option} value={option}>{optionLabel(option)}</SelectItem>)}</SelectContent>
    </Select>
  </div>;
}

/** Plan and launch for the current document. One primary action; the stage-by-stage actions are secondary. */
export function PipelineLauncher({ context }: { context: ActiveContext }) {
  const api = useApi();
  const can = useCapability();
  const { advanced } = useMode();
  const { t } = useT();
  const navigate = useNavigate();
  const [format, setFormat] = useState<OutputFormat>("docx");
  const [chosenPolicy, setPolicy] = useState<RunPolicy>("draft");
  // "release" only exists under Advanced; turning Advanced off must not leave it selected.
  const policy: RunPolicy = !advanced && chosenPolicy === "release" ? "draft" : chosenPolicy;
  const { workspaceId, documentId } = context;

  const plan = useQuery({
    queryKey: ["pipeline", workspaceId, documentId, "plan", format],
    queryFn: () => api.planPipeline!(documentId!, { format }),
    enabled: !!documentId && !!api.planPipeline && can("document.plan"),
  });

  const openRun = (result: { id?: unknown }) => { if (result.id) navigate(`/pipeline/runs/${encodeURIComponent(String(result.id))}`); };
  const invalidate = [["pipeline", workspaceId, "runs"]];
  const run = useAction(() => api.runDocument!(documentId!, { format, policy }), { success: result => t("pl.started", { id: String(result.id) }), invalidate, onDone: openRun });
  const step = useAction((kind: "prepare" | "build" | "verify") => api.documentAction!(documentId!, kind, workspaceId!, format), {
    success: (result, kind) => kind === "prepare" ? t("pl.prepared", { id: documentId! }) : t("pl.startedStep", { kind: t(`pl.step.${kind}`).toLowerCase(), id: String(result.id ?? "") }),
    invalidate,
    onDone: (result, kind) => { if (kind !== "prepare") openRun(result); },
  });

  if (!documentId) return <EmptyState title={t("pl.selectDoc.title")} description={t("pl.selectDoc.body")}>
    <Button asChild><Link to="/configure/workspaces">{t("pl.openWorkspaces")}</Link></Button>
  </EmptyState>;

  const busy = run.isPending || step.isPending;
  return <section aria-label={t("pl.launch")} className="grid gap-4 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-end gap-4">
      <Choice id="pipeline-format" label={t("pl.format")} value={format} options={formats} onChange={next => setFormat(next as OutputFormat)} />
      <Choice id="pipeline-policy" label={t("pl.policy")} value={policy} options={advanced ? policies : policies.filter(item => item !== "release")} optionLabel={option => t(`pl.policy.${option as RunPolicy}`)} onChange={next => setPolicy(next as RunPolicy)} />
    </div>
    {can("document.plan") && api.planPipeline && <QueryBoundary query={plan} title={t("pl.planFailed")} skeleton="h-16 w-full">{data => <div className="grid gap-2 text-sm">
        <p className="font-medium">{t("pl.planFor", { document: data.document_id, pipeline: data.pipeline_id })}</p>
        <ol aria-label={t("pl.stages")} className="flex flex-wrap gap-2">{data.stages.map(stage => <li key={stage} className="rounded-md border px-2 py-1">{stage}</li>)}</ol>
        {data.external_artifacts.length > 0 && <div className="flex flex-wrap items-center gap-2"><span className="text-muted-foreground">{t("pl.needs")}</span>
          <ul className="flex flex-wrap gap-2">{data.external_artifacts.map(name => <li key={name} className="rounded-md bg-muted px-2 py-0.5">{name}</li>)}</ul></div>}
      </div>}</QueryBoundary>}
    <div className="flex flex-wrap items-center gap-2">
      {can("document.run") && api.runDocument && <Button id={focusTargets.runPipeline} type="button" disabled={busy} onClick={() => run.mutate(undefined)}>{t("pl.run")}</Button>}
      {api.documentAction && stageActions.filter(([, capability]) => can(capability)).map(([kind]) =>
        <Button key={kind} type="button" variant="outline" disabled={busy} onClick={() => step.mutate(kind)}>{t(`pl.step.${kind}`)}</Button>)}
    </div>
    <p className="text-sm text-muted-foreground">{t("pipeline.deliverHint")} <Link className="font-medium underline underline-offset-4" to="/delivery">{t("term.deliver")}</Link></p>
    <ActionError action={run} what={t("act.startRun")} />
    <ActionError action={step} what={t("act.runStep")} />
  </section>;
}
