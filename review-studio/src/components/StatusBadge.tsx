import type { Status } from "../api/models";
import { cn } from "@/lib/utils";

const label = { passed: "Passed", warnings: "Warnings", failed: "Failed", unverified: "Unverified" } as const;
const glyph = { passed: "✓", failed: "×", warnings: "!", unverified: "?" } as const;
const tone = {
  passed: "border-success/40 text-success", warnings: "border-warning/50 text-warning",
  failed: "border-destructive/40 text-destructive", unverified: "border-border text-muted-foreground",
} as const;

export function StatusBadge({ status }: { status: Status }) {
  return <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-semibold whitespace-nowrap", tone[status])}><span aria-hidden="true">{glyph[status]}</span> {label[status]}</span>;
}
