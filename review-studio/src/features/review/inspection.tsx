import { formatApiError } from "@/api/errors";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import { useMode } from "@/app/mode";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import type { Artifact } from "@/api/models";
import type { ArtifactReport } from "@/api/domains/review";
import { Skeleton } from "@/components/ui/skeleton";

import { Digest, Facts } from "@/components/shared/Facts";
import { reviewKeys } from "./data";

/** The structured inspect report for one artifact: where it lives, what it is, and its digest. */
export type ReportRow = { label: string; value: React.ReactNode; /** Technical detail shown only when Advanced is on. */ advancedOnly?: boolean };
export const reportRows = (report: ArtifactReport): ReportRow[] => [
  { label: "Path", value: report.path }, { label: "Media type", value: report.media_type }, { label: "Size", value: `${report.size_bytes} bytes` },
  { label: "SHA-256", value: <Digest value={report.sha256} />, advancedOnly: true },
];
/** Rows as the Facts list takes them; Advanced-only rows drop out unless `advanced`. */
export const factRows = (rows: ReportRow[], advanced = true): Array<[string, React.ReactNode]> =>
  rows.filter(row => advanced || !row.advancedOnly).map(row => [row.label, row.value]);

export function InspectionPanel({ workspaceId, artifactId }: { workspaceId: string | null; artifactId: string }) {
  const api = useApi();
  const { advanced } = useMode();
  const report = useQuery({ queryKey: reviewKeys.inspect(workspaceId, artifactId), queryFn: () => api.inspectArtifact!(artifactId) });
  return <QueryBoundary query={report} title="Could not inspect the artifact" skeleton="h-16 w-full">{data =>
    <section aria-label="Inspection" className="grid gap-2 rounded-md border p-3"><h3 className="font-semibold">Inspection</h3><Facts rows={factRows(reportRows(data), advanced)} /></section>}</QueryBoundary>;
}

/** Page previews for an artifact. Every failure path says what is missing instead of leaving a blank box. */
export function ArtifactPreview({ workspaceId, artifact }: { workspaceId: string | null; artifact: Artifact }) {
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
  else if (previews.isError) body = <p role="status" className="text-sm text-muted-foreground">Previews could not be loaded. {formatApiError(previews.error)}</p>;
  else if (previews.data.length === 0) body = <p role="status" className="text-sm text-muted-foreground">No rendered previews exist for this artifact. Page previews need a render toolchain such as LibreOffice; the file itself can still be inspected.</p>;
  else body = <ul className="grid gap-3 sm:grid-cols-2">{previews.data.map((preview, index) => {
    const url = urlFor(preview.id);
    return <li key={preview.id} className="rounded-md border p-2">
      {url && !broken.has(preview.id)
        ? <img src={url} alt={`Page preview ${index + 1} of ${artifact.name}`} loading="lazy" className="w-full" onError={() => setBroken(current => new Set(current).add(preview.id))} />
        : <p role="status" className="text-sm text-muted-foreground">Preview image unavailable for {preview.id}.</p>}
    </li>;
  })}</ul>;
  return <section aria-label="Previews" className="grid gap-2"><h3 className="font-semibold">Previews</h3>{body}</section>;
}
