import { useT } from "@/lib/i18n";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import type { ArtifactDiff } from "@/api/domains/review";
import type { Artifact } from "@/api/models";
import { EmptyState } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ActionError, useAction } from "@/lib/actions";
import { Unavailable } from "@/components/shared/Unavailable";
import { useCapability } from "@/lib/capability-registry";
import { Facts } from "@/components/shared/Facts";
import { reviewKeys } from "./data";
import { factRows, reportRows } from "./inspection";

const SHOWN_LINES = 200;
const lineClass = (line: string) => line.startsWith("+") && !line.startsWith("+++") ? "bg-emerald-500/15" : line.startsWith("-") && !line.startsWith("---") ? "bg-red-500/15" : "text-muted-foreground";

/** A text diff in a bounded scroll area; long diffs are cut until the user asks for all of it. */
export function DiffViewer({ diff }: { diff: ArtifactDiff }) {
  const { t } = useT();
  const [all, setAll] = useState(false);
  const lines = all ? diff.text_diff : diff.text_diff.slice(0, SHOWN_LINES);
  return <section aria-label={t("rv.diff.differences")} className="grid gap-3 rounded-lg border bg-card p-4">
    <h3 className="text-lg font-semibold">{diff.same ? t("rv.diff.same") : t("rv.diff.differ")}</h3>
    <div className="grid gap-4 sm:grid-cols-2">
      <div><p className="mb-1 text-sm font-medium">{t("rv.diff.left")}</p><Facts rows={factRows(reportRows(diff.left), t)} /></div>
      <div><p className="mb-1 text-sm font-medium">{t("rv.diff.right")}</p><Facts rows={factRows(reportRows(diff.right), t)} /></div>
    </div>
    {diff.text_diff.length > 0 && <>
      <div className="max-h-96 overflow-auto rounded-md border font-mono text-xs" tabIndex={0} aria-label={t("rv.diff.lines")}>
        {lines.map((line, index) => <div key={index} className={`px-2 whitespace-pre-wrap break-all ${lineClass(line)}`}>{line || " "}</div>)}
      </div>
      {!all && diff.text_diff.length > SHOWN_LINES && <Button type="button" variant="outline" className="w-fit" onClick={() => setAll(true)}>{t("rv.diff.showAll", { count: diff.text_diff.length })}</Button>}
    </>}
    {diff.text_diff.length === 0 && !diff.same && <p className="text-sm text-muted-foreground">{t("rv.diff.binary")}</p>}
  </section>;
}

function DiffForm({ artifacts }: { artifacts: Artifact[] }) {
  const api = useApi();
  const { t } = useT();
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [result, setResult] = useState<ArtifactDiff | null>(null);
  const compare = useAction(() => api.diffArtifacts!(left, right), { success: () => t("rv.diff.ready"), onDone: setResult });
  if (artifacts.length < 2) return <EmptyState title={t("rv.diff.none.title")} description={t("rv.diff.none.body")} action={{ label: t("empty.runPipeline"), to: "/pipeline" }} />;
  const picker = (side: string, label: string, value: string, set: (id: string) => void) => <div className="grid gap-1"><Label htmlFor={`diff-${side}`}>{label}</Label>
    <Select value={value} onValueChange={id => { set(id); setResult(null); compare.reset(); }}>
      <SelectTrigger id={`diff-${side}`} aria-label={label} className="w-64"><SelectValue placeholder={t("rv.diff.choose")} /></SelectTrigger>
      <SelectContent>{artifacts.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent>
    </Select></div>;
  return <div className="grid gap-4">
    <div className="flex flex-wrap items-end gap-4">
      {picker("left", t("rv.diff.leftArtifact"), left, setLeft)}{picker("right", t("rv.diff.rightArtifact"), right, setRight)}
      <Button type="button" disabled={!left || !right || left === right || compare.isPending} onClick={() => compare.mutate(undefined)}>{t("rv.diff.compare")}</Button>
    </div>
    {left && left === right && <p className="text-sm text-muted-foreground" role="status">{t("rv.diff.different")}</p>}
    <ActionError action={compare} what={t("act.compareArtifacts")} />
    {result && <DiffViewer diff={result} />}
  </div>;
}

export function DiffPanel({ workspaceId }: { workspaceId: string | null }) {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const artifacts = useQuery({ queryKey: reviewKeys.artifacts(workspaceId), queryFn: () => api.listArtifacts() });
  if (!can("document.diff") || !api.diffArtifacts) return <Unavailable>{t("rv.diff.unavailable")}</Unavailable>;
  return <QueryBoundary query={artifacts} title={t("rv.art.loadFailed")}>{list => <DiffForm artifacts={list} />}</QueryBoundary>;
}
