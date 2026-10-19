import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

export const deliveryKeys = {
  publications: (ws: string | null) => ["delivery", ws, "publications"],
  runs: (ws: string | null, documentId: string) => ["delivery", ws, "runs", documentId],
};

/** First 12 characters of a digest; the full value is one click away on the copy button. */
const shortDigest = (value: string) => value ? `${value.slice(0, 12)}…` : "-";

export function CopyDigest({ value }: { value: string }) {
  const { t } = useT();
  const label = t("dl.digest");
  if (!value) return <span>-</span>;
  const copy = () => {
    // ponytail: clipboard may be missing (insecure context); the toast says so rather than pretending.
    const write = navigator.clipboard?.writeText(value);
    if (!write) { toast.error(t("dl.copyUnavailable")); return; }
    write.then(() => toast.success(t("dl.copied", { label })), () => toast.error(t("dl.copyFailed")));
  };
  return <span className="inline-flex items-center gap-1">
    <code className="text-xs" title={value}>{shortDigest(value)}</code>
    <Button type="button" variant="ghost" size="sm" className="h-6 px-1 text-xs" aria-label={t("dl.copyLabel", { label, value: shortDigest(value) })} onClick={copy}>{t("dl.copy")}</Button>
  </span>;
}
