import type { ReactNode } from "react";
import { useT } from "@/lib/i18n";

const scalar = (value: unknown) => ["string", "number", "boolean"].includes(typeof value) || value === null;
const show = (value: unknown) => value === null ? "-" : String(value);

/** A server record as readable nested labels and values. Structure is rendered, never dumped as JSON. */
export function StructureView({ value, label }: { value: unknown; label?: string }): ReactNode {
  const { t } = useT();
  if (scalar(value)) return <span className="break-words">{show(value)}</span>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted-foreground">{t("common.none")}</span>;
    if (value.every(scalar)) return <span className="break-words">{value.map(show).join(", ")}</span>;
    return <ol aria-label={label} className="grid list-decimal gap-2 pl-5">{value.map((item, index) => <li key={index}><StructureView value={item} /></li>)}</ol>;
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return <span className="text-muted-foreground">{t("common.empty")}</span>;
  return <dl aria-label={label} className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[minmax(8rem,12rem)_1fr]">
    {entries.map(([key, entry]) => <div key={key} className="contents">
      <dt className="text-muted-foreground">{key}</dt><dd className="min-w-0"><StructureView value={entry} /></dd>
    </div>)}
  </dl>;
}
