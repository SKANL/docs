import { formatApiError } from "@/api/errors";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import type { ArtifactDiff } from "@/api/domains/review";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ActionError, useAction } from "@/lib/actions";
import { Unavailable } from "@/components/shared/Unavailable";
import { useCapability } from "@/lib/capability-registry";
import { Facts } from "@/components/shared/Facts";
import { reviewKeys } from "./data";
import { reportRows } from "./inspection";

const SHOWN_LINES = 200;
const lineClass = (line: string) => line.startsWith("+") && !line.startsWith("+++") ? "bg-emerald-500/15" : line.startsWith("-") && !line.startsWith("---") ? "bg-red-500/15" : "text-muted-foreground";

/** A text diff in a bounded scroll area; long diffs are cut until the user asks for all of it. */
export function DiffViewer({ diff }: { diff: ArtifactDiff }) {
  const [all, setAll] = useState(false);
  const lines = all ? diff.text_diff : diff.text_diff.slice(0, SHOWN_LINES);
  return <section aria-label="Differences" className="grid gap-3 rounded-lg border bg-card p-4">
    <h3 className="text-lg font-semibold">{diff.same ? "The artifacts are identical." : "The artifacts differ."}</h3>
    <div className="grid gap-4 sm:grid-cols-2">
      <div><p className="mb-1 text-sm font-medium">Left</p><Facts rows={reportRows(diff.left)} /></div>
      <div><p className="mb-1 text-sm font-medium">Right</p><Facts rows={reportRows(diff.right)} /></div>
    </div>
    {diff.text_diff.length > 0 && <>
      <div className="max-h-96 overflow-auto rounded-md border font-mono text-xs" tabIndex={0} aria-label="Diff lines">
        {lines.map((line, index) => <div key={index} className={`px-2 whitespace-pre-wrap break-all ${lineClass(line)}`}>{line || " "}</div>)}
      </div>
      {!all && diff.text_diff.length > SHOWN_LINES && <Button type="button" variant="outline" className="w-fit" onClick={() => setAll(true)}>Show all {diff.text_diff.length} lines</Button>}
    </>}
    {diff.text_diff.length === 0 && !diff.same && <p className="text-sm text-muted-foreground">The files differ, but they have no textual diff (binary content). Compare their digests above.</p>}
  </section>;
}

export function DiffPanel({ workspaceId }: { workspaceId: string | null }) {
  const api = useApi();
  const can = useCapability();
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [result, setResult] = useState<ArtifactDiff | null>(null);
  const artifacts = useQuery({ queryKey: reviewKeys.artifacts(workspaceId), queryFn: () => api.listArtifacts() });
  const compare = useAction(() => api.diffArtifacts!(left, right), { success: () => "Comparison ready.", onDone: setResult });
  if (!can("document.diff") || !api.diffArtifacts) return <Unavailable>Artifact comparison is not available on this server.</Unavailable>;
  if (artifacts.isPending) return <Skeleton className="h-24 w-full" />;
  if (artifacts.isError) return <ErrorState title="Could not load artifacts" message={formatApiError(artifacts.error)} onRetry={() => void artifacts.refetch()} />;
  if (artifacts.data.length < 2) return <EmptyState title="Nothing to compare yet" description="Comparing needs two artifacts. Build the document again to produce a second one." />;
  const picker = (label: string, value: string, set: (id: string) => void) => <div className="grid gap-1"><Label htmlFor={`diff-${label}`}>{label}</Label>
    <Select value={value} onValueChange={id => { set(id); setResult(null); compare.reset(); }}>
      <SelectTrigger id={`diff-${label}`} aria-label={label} className="w-64"><SelectValue placeholder="Choose an artifact" /></SelectTrigger>
      <SelectContent>{artifacts.data.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent>
    </Select></div>;
  return <div className="grid gap-4">
    <div className="flex flex-wrap items-end gap-4">
      {picker("Left artifact", left, setLeft)}{picker("Right artifact", right, setRight)}
      <Button type="button" disabled={!left || !right || left === right || compare.isPending} onClick={() => compare.mutate(undefined)}>Compare</Button>
    </div>
    {left && left === right && <p className="text-sm text-muted-foreground" role="status">Choose two different artifacts.</p>}
    <ActionError action={compare} what="compare the artifacts" />
    {result && <DiffViewer diff={result} />}
  </div>;
}
