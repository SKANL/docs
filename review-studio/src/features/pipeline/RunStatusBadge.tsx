import { Badge } from "@/components/ui/badge";

const variant = (status: string) => status === "succeeded" || status === "completed" ? "default" : status === "failed" || status === "expired" ? "destructive" : status === "cancelled" ? "outline" : "secondary";

export function RunStatusBadge({ status }: { status: string }) {
  return <Badge variant={variant(status)}>{status}</Badge>;
}
