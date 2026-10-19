import type { Status } from "@/api/models";
import { useT } from "@/lib/i18n";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type Tone = "success" | "warning" | "danger" | "muted" | "neutral";

/** The one place a status word becomes a tone, for review statuses and run lifecycle statuses alike. */
const toneOf = (status: string): Tone => ({
  passed: "success", succeeded: "success", completed: "success",
  warnings: "warning",
  failed: "danger", expired: "danger",
  cancelled: "muted",
} as Record<string, Tone>)[status] ?? "neutral";

const glyph = { success: "✓", danger: "×", warning: "!", muted: "?", neutral: "?" } as const;
const pill = {
  success: "border-success/40 text-success", warning: "border-warning/50 text-warning",
  danger: "border-destructive/40 text-destructive", muted: "border-border text-muted-foreground", neutral: "border-border text-muted-foreground",
} as const;
const badge = { success: "default", danger: "destructive", muted: "outline", warning: "secondary", neutral: "secondary" } as const;

/** A review verdict (artifact, baseline) as a labelled pill with a glyph, so colour is never the only signal. */
export function StatusBadge({ status }: { status: Status }) {
  const { t } = useT();
  const tone = toneOf(status);
  return <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-semibold whitespace-nowrap", pill[tone])}><span aria-hidden="true">{glyph[tone]}</span> {t(`status.${status}`)}</span>;
}

/** A run's lifecycle status, shown as the server words it. */
export function RunStatusBadge({ status }: { status: string }) {
  return <Badge variant={badge[toneOf(status)]}>{status}</Badge>;
}
