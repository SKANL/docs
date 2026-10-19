import { Badge } from "@/components/ui/badge";
import { statusKey, useT, type MessageKey } from "@/lib/i18n";

type Translate = (key: MessageKey, vars?: Record<string, string | number>) => string;

/** Query keys are workspace-scoped so switching workspaces never shows another workspace's evidence. */
export const reviewKeys = {
  findings: (ws: string | null) => ["review", ws, "findings"],
  artifacts: (ws: string | null) => ["review", ws, "artifacts"],
  runs: (ws: string | null) => ["review", ws, "runs"],
  evidence: (ws: string | null, runId: string) => ["review", ws, "evidence", runId],
  previews: (ws: string | null, artifactId: string) => ["review", ws, "previews", artifactId],
  inspect: (ws: string | null, artifactId: string) => ["review", ws, "inspect", artifactId],
  baselines: (ws: string | null) => ["review", ws, "baselines"],
  baseline: (ws: string | null, id: string) => ["review", ws, "baseline", id],
  graph: (ws: string | null) => ["review", ws, "graph"],
};

const text = (value: unknown) => typeof value === "string" && value ? value : undefined;

/** A finding reduced to what the UI shows. Server findings vary in field names, so every read is tolerant. */
export interface FindingRow {
  id: string; runId?: string; severity: string; status?: string; message: string; code?: string;
  section?: string; file?: string; page?: number; evidence?: string; location: string;
}

export function toFindingRow(raw: Record<string, unknown>): FindingRow {
  const section = text(raw.section);
  const file = text(raw.file);
  const page = typeof raw.page === "number" ? raw.page : undefined;
  return {
    id: String(raw.id ?? ""), runId: text(raw.runId) ?? text(raw.run_id), severity: text(raw.severity) ?? "unknown", status: text(raw.status),
    message: text(raw.message) ?? text(raw.title) ?? text(raw.summary) ?? "", code: text(raw.code),
    section, file, page, evidence: text(raw.evidence), location: text(raw.location) ?? "",
  };
}

/** Where a finding is, in words: the server's own location, else section / file / page, else "-". */
export const findingLocation = (row: FindingRow, t: Translate) =>
  row.location || [row.section && t("sec.whereSection", { id: row.section }), row.file, row.page !== undefined && t("sec.wherePage", { page: row.page })].filter(Boolean).join(" · ") || "-";

export function SeverityBadge({ severity }: { severity: string }) {
  const { t } = useT();
  const key = statusKey("rv.sev", severity);
  const variant = severity === "critical" || severity === "high" ? "destructive" : severity === "low" ? "outline" : "secondary";
  return <Badge variant={variant}>{key ? t(key) : severity}</Badge>;
}
