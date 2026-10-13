import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";

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
  const where = [section && `section ${section}`, file, page !== undefined && `page ${page}`].filter(Boolean).join(" · ");
  return {
    id: String(raw.id ?? ""), runId: text(raw.runId) ?? text(raw.run_id), severity: text(raw.severity) ?? "unknown", status: text(raw.status),
    message: text(raw.message) ?? text(raw.title) ?? text(raw.summary) ?? "No description", code: text(raw.code),
    section, file, page, evidence: text(raw.evidence), location: text(raw.location) ?? (where || "-"),
  };
}

export function SeverityBadge({ severity }: { severity: string }) {
  const variant = severity === "critical" || severity === "high" ? "destructive" : severity === "low" ? "outline" : "secondary";
  return <Badge variant={variant}>{severity}</Badge>;
}

/** Label/value pairs; empty values are skipped. */
export function Facts({ rows, label }: { rows: Array<[string, ReactNode | undefined]>; label?: string }) {
  return <dl aria-label={label} className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[10rem_1fr]">
    {rows.filter(([, value]) => value !== undefined && value !== "").map(([name, value]) => <div key={name} className="contents">
      <dt className="text-muted-foreground">{name}</dt><dd className="min-w-0 break-all">{value}</dd>
    </div>)}
  </dl>;
}

/** Readable rows for a server record: scalars and lists of scalars only; nested structures are skipped, never dumped. */
export function scalarRows(record: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(record).flatMap(([key, value]): Array<[string, string]> => {
    if (["string", "number", "boolean"].includes(typeof value)) return [[key, String(value)]];
    if (Array.isArray(value) && value.length && value.every(entry => ["string", "number"].includes(typeof entry))) return [[key, value.join(", ")]];
    return [];
  });
}

export const Digest = ({ value }: { value: string }) => <code className="text-xs break-all">{value || "-"}</code>;
