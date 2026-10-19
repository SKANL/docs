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
import { useCapability } from "@/lib/capability-registry";
import { type ActiveContext } from "@/app/active-context";
import type { OutputFormat, RunPolicy } from "@/api/domains/pipeline";

const formats: OutputFormat[] = ["docx", "pdf", "html"];
const policies: RunPolicy[] = ["draft", "strict", "release"];
const stageActions = [["prepare", "Prepare", "document.prepare"], ["build", "Build", "document.build"], ["verify", "Verify", "document.verify"]] as const;

function Choice({ label, value, options, onChange }: { label: string; value: string; options: readonly string[]; onChange(value: string): void }) {
  const id = `pipeline-${label.toLowerCase().replace(/\W+/g, "-")}`;
  return <div className="grid gap-1">
    <Label htmlFor={id}>{label}</Label>
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id} aria-label={label} className="w-36"><SelectValue /></SelectTrigger>
      <SelectContent>{options.map(option => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent>
    </Select>
  </div>;
}

/** Plan and launch for the current document. One primary action; the stage-by-stage actions are secondary. */
export function PipelineLauncher({ context }: { context: ActiveContext }) {
  const api = useApi();
  const can = useCapability();
  const navigate = useNavigate();
  const [format, setFormat] = useState<OutputFormat>("docx");
  const [policy, setPolicy] = useState<RunPolicy>("draft");
  const { workspaceId, documentId } = context;

  const plan = useQuery({
    queryKey: ["pipeline", workspaceId, documentId, "plan", format],
    queryFn: () => api.planPipeline!(documentId!, { format }),
    enabled: !!documentId && !!api.planPipeline && can("document.plan"),
  });

  const openRun = (result: { id?: unknown }) => { if (result.id) navigate(`/pipeline/runs/${encodeURIComponent(String(result.id))}`); };
  const invalidate = [["pipeline", workspaceId, "runs"]];
  const run = useAction(() => api.runDocument!(documentId!, { format, policy }), { success: result => `Started run ${result.id}.`, invalidate, onDone: openRun });
  const step = useAction((kind: "prepare" | "build" | "verify") => api.documentAction!(documentId!, kind, workspaceId!, format), {
    success: (result, kind) => kind === "prepare" ? `Prepared ${documentId}.` : `Started ${kind} run ${String(result.id ?? "")}`.trim() + ".",
    invalidate,
    onDone: (result, kind) => { if (kind !== "prepare") openRun(result); },
  });

  if (!documentId) return <EmptyState title="Select a document first" description="The pipeline runs against the current document. Choose or create one before planning a run.">
    <Button asChild><Link to="/configure/workspaces">Open workspaces and documents</Link></Button>
  </EmptyState>;

  const busy = run.isPending || step.isPending;
  return <section aria-label="Launch" className="grid gap-4 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-end gap-4">
      <Choice label="Output format" value={format} options={formats} onChange={next => setFormat(next as OutputFormat)} />
      <Choice label="Policy" value={policy} options={policies} onChange={next => setPolicy(next as RunPolicy)} />
    </div>
    {can("document.plan") && api.planPipeline && <QueryBoundary query={plan} title="Could not plan the pipeline" skeleton="h-16 w-full">{data => <div className="grid gap-2 text-sm">
        <p className="font-medium">Plan for {data.document_id} ({data.pipeline_id})</p>
        <ol aria-label="Pipeline stages" className="flex flex-wrap gap-2">{data.stages.map(stage => <li key={stage} className="rounded-md border px-2 py-1">{stage}</li>)}</ol>
        {data.external_artifacts.length > 0 && <div className="flex flex-wrap items-center gap-2"><span className="text-muted-foreground">Needs these inputs:</span>
          <ul className="flex flex-wrap gap-2">{data.external_artifacts.map(name => <li key={name} className="rounded-md bg-muted px-2 py-0.5">{name}</li>)}</ul></div>}
      </div>}</QueryBoundary>}
    <div className="flex flex-wrap items-center gap-2">
      {can("document.run") && api.runDocument && <Button id={focusTargets.runPipeline} type="button" disabled={busy} onClick={() => run.mutate(undefined)}>Run pipeline</Button>}
      {api.documentAction && stageActions.filter(([, , capability]) => can(capability)).map(([kind, label]) =>
        <Button key={kind} type="button" variant="outline" disabled={busy} onClick={() => step.mutate(kind)}>{label}</Button>)}
    </div>
    <ActionError action={run} what="start the run" />
    <ActionError action={step} what="run the step" />
  </section>;
}
