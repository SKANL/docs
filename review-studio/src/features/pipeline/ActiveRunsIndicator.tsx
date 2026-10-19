import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { useCapability } from "@/lib/capability-registry";
import { useT } from "@/lib/i18n";

/** Topbar chip: how many runs are in flight in the current workspace. Renders nothing when idle or unsupported. */
export function ActiveRunsIndicator() {
  const api = useApi();
  const can = useCapability();
  const { t } = useT();
  const running = useQuery({
    // ponytail: keyed without the workspace (the client resolves the selected one per call); the 4s poll corrects a switch.
    queryKey: ["pipeline", "running-count"],
    queryFn: () => api.listRunPage!({ status: "running", limit: 20 }),
    enabled: !!api.listRunPage && can("run.list"),
    refetchInterval: 4_000,
  });
  const count = running.data?.items.length ?? 0;
  if (count === 0) return null;
  return <Link to="/pipeline" className="flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs" aria-label={t(count === 1 ? "runs.activeLabel.one" : "runs.activeLabel.other", { count })}>
    <Loader2 aria-hidden="true" className="size-3.5 animate-spin" />{t("runs.active", { count })}
  </Link>;
}
