import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import { useMode } from "@/app/mode";
import { ErrorState } from "@/components/shared/ErrorState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import type { Artifact } from "@/api/models";
import type { ArtifactReport } from "@/api/domains/review";
import { Skeleton } from "@/components/ui/skeleton";
import { useT, type MessageKey } from "@/lib/i18n";

import { Digest, Facts } from "@/components/shared/Facts";
import { reviewKeys } from "./data";

/** The structured inspect report for one artifact: where it lives, what it is, and its digest. */
export type ReportRow = { label: MessageKey; value: React.ReactNode; /** Technical detail shown only when Advanced is on. */ advancedOnly?: boolean };
export const reportRows = (report: ArtifactReport): ReportRow[] => [
  { label: "rv.insp.path", value: report.path }, { label: "rv.insp.media", value: report.media_type }, { label: "rv.insp.size", value: `${report.size_bytes} bytes` },
  { label: "rv.insp.sha", value: <Digest value={report.sha256} />, advancedOnly: true },
];
/** Rows as the Facts list takes them; Advanced-only rows drop out unless `advanced`. */
export const factRows = (rows: ReportRow[], t: (key: MessageKey) => string, advanced = true): Array<[string, React.ReactNode]> =>
  rows.filter(row => advanced || !row.advancedOnly).map(row => [t(row.label), row.value]);

export function InspectionPanel({ workspaceId, artifactId }: { workspaceId: string | null; artifactId: string }) {
  const { t } = useT();
  const api = useApi();
  const { advanced } = useMode();
  const report = useQuery({ queryKey: reviewKeys.inspect(workspaceId, artifactId), queryFn: () => api.inspectArtifact!(artifactId) });
  return <QueryBoundary query={report} title={t("rv.insp.failed")} skeleton="h-16 w-full">{data =>
    <section aria-label={t("rv.insp.title")} className="grid gap-2 rounded-md border p-3"><h3 className="font-semibold">{t("rv.insp.title")}</h3><Facts rows={factRows(reportRows(data), t, advanced)} /></section>}</QueryBoundary>;
}

/** Page previews for an artifact. Every failure path says what is missing instead of leaving a blank box. */
export function ArtifactPreview({ workspaceId, artifact }: { workspaceId: string | null; artifact: Artifact }) {
  const { t } = useT();
  const api = useApi();
  const [broken, setBroken] = useState<Set<string>>(new Set());
  const previews = useQuery({
    queryKey: reviewKeys.previews(workspaceId, artifact.id),
    // A PNG artifact is its own preview; anything else lists the PNG pages rendered from it.
    queryFn: async () => artifact.kind === "PNG" ? [{ id: artifact.id }] : ((await api.listArtifactPreviews?.(artifact.id)) ?? []).map(item => ({ id: String(item.id ?? "") })).filter(item => item.id),
  });
  const urlFor = (previewId: string) => { try { return artifact.runId ? api.artifactPreviewUrl?.(artifact.runId, previewId) : undefined; } catch { return undefined; } };
  let body: React.ReactNode;
  if (previews.isPending) body = <Skeleton className="h-24 w-full" />;
  else if (previews.isError) body = <ErrorState title={t("rv.prev.loadFailed")} error={previews.error} />;
  else if (previews.data.length === 0) body = <p role="status" className="text-sm text-muted-foreground">{t("rv.prev.none")}</p>;
  else body = <ul className="grid gap-3 sm:grid-cols-2">{previews.data.map((preview, index) => {
    const url = urlFor(preview.id);
    return <li key={preview.id} className="rounded-md border p-2">
      {url && !broken.has(preview.id)
        ? <img src={url} alt={t("rv.prev.alt", { n: index + 1, name: artifact.name })} loading="lazy" className="w-full" onError={() => setBroken(current => new Set(current).add(preview.id))} />
        : <p role="status" className="text-sm text-muted-foreground">{t("rv.prev.unavailable", { id: preview.id })}</p>}
    </li>;
  })}</ul>;
  return <section aria-label={t("rv.prev.title")} className="grid gap-2"><h3 className="font-semibold">{t("rv.prev.title")}</h3>{body}</section>;
}
