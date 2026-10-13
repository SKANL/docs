import { useNavigate } from "react-router-dom";
import { useApi } from "@/app/providers";
import { Button } from "@/components/ui/button";
import { ActionError, useAction } from "@/features/authoring/data";

/** A release is a pipeline run with policy "release". Whether it may proceed is the server's call, reported on the run. */
export function ReleasePanel({ workspaceId, documentId }: { workspaceId: string | null; documentId: string }) {
  const api = useApi();
  const navigate = useNavigate();
  const release = useAction(() => api.runDocument!(documentId, { policy: "release" }), {
    success: result => `Started release run ${result.id}.`,
    invalidate: [["pipeline", workspaceId, "runs"]],
    onDone: result => { if (result.id) navigate(`/pipeline/runs/${encodeURIComponent(String(result.id))}`); },
  });
  return <section aria-label="Release" className="grid gap-3 rounded-lg border bg-card p-4">
    <h2 className="text-xl font-semibold">Release</h2>
    <p className="text-sm text-muted-foreground">Starts a pipeline run with the release policy for {documentId}. Approval and eligibility are decided by the server; any denial is shown on the run, and a started run is not a release until it succeeds.</p>
    <Button type="button" className="w-fit" disabled={release.isPending} onClick={() => release.mutate(undefined)}>Start release run</Button>
    <ActionError action={release} what="start the release run" />
  </section>;
}
