import type { ReactNode } from "react";

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
