import { useNavigate } from "react-router-dom";
import { useApi } from "@/app/providers";
import { Button } from "@/components/ui/button";
import { ActionError, useAction } from "@/lib/actions";
import { useT } from "@/lib/i18n";

/** A release is a pipeline run with policy "release". Whether it may proceed is the server's call, reported on the run. */
export function ReleasePanel({ workspaceId, documentId }: { workspaceId: string | null; documentId: string }) {
  const { t } = useT();
  const api = useApi();
  const navigate = useNavigate();
  const release = useAction(() => api.runDocument!(documentId, { policy: "release" }), {
    success: result => t("dl.rel.toast", { id: String(result.id) }),
    invalidate: [["pipeline", workspaceId, "runs"]],
    onDone: result => { if (result.id) navigate(`/pipeline/runs/${encodeURIComponent(String(result.id))}`); },
  });
  return <section aria-label={t("dl.rel.heading")} className="grid gap-3 rounded-lg border bg-card p-4">
    <h2 className="text-xl font-semibold">{t("dl.rel.heading")}</h2>
    <p className="text-sm text-muted-foreground">{t("dl.rel.body", { id: documentId })}</p>
    <Button type="button" className="w-fit" disabled={release.isPending} onClick={() => release.mutate(undefined)}>{t("dl.rel.start")}</Button>
    <ActionError action={release} what={t("act.release")} />
  </section>;
}
