import { toast } from "sonner";
import { Button } from "@/components/ui/button";

export const deliveryKeys = {
  publications: (ws: string | null) => ["delivery", ws, "publications"],
  runs: (ws: string | null, documentId: string) => ["delivery", ws, "runs", documentId],
};

/** First 12 characters of a digest; the full value is one click away on the copy button. */
export const shortDigest = (value: string) => value ? `${value.slice(0, 12)}…` : "-";

export function CopyDigest({ value, label = "digest" }: { value: string; label?: string }) {
  if (!value) return <span>-</span>;
  const copy = () => {
    // ponytail: clipboard may be missing (insecure context); the toast says so rather than pretending.
    const write = navigator.clipboard?.writeText(value);
    if (!write) { toast.error("Copying is not available in this browser."); return; }
    write.then(() => toast.success(`Copied ${label}.`), () => toast.error("Could not copy."));
  };
  return <span className="inline-flex items-center gap-1">
    <code className="text-xs" title={value}>{shortDigest(value)}</code>
    <Button type="button" variant="ghost" size="sm" className="h-6 px-1 text-xs" aria-label={`Copy ${label} ${shortDigest(value)}`} onClick={copy}>Copy</Button>
  </span>;
}
