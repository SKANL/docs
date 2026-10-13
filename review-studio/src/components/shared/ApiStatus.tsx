import { useEffect, useState } from "react";
import type { ReviewApi } from "@/api/models";
import { formatApiError } from "@/api/errors";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type ApiHealth = { state: "checking" | "ready" | "unavailable"; detail: string; readyEpoch: number };

/** Poll the service health until it is ready: the desktop sidecar cold-starts after the UI renders. */
export function useApiHealth(api: ReviewApi, pollIntervalMs = 2000): ApiHealth {
  const [health, setHealth] = useState<ApiHealth>({ state: "checking", detail: "", readyEpoch: 0 });
  useEffect(() => {
    if (!api.health) { setHealth(current => ({ ...current, state: "unavailable", detail: "Health endpoint is not available" })); return; }
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = () => {
      api.health!().then(value => {
        if (!active) return;
        if (value.ready) setHealth(current => ({ state: "ready", detail: value.protocol ?? "", readyEpoch: current.state === "unavailable" ? current.readyEpoch + 1 : current.readyEpoch }));
        else { setHealth(current => ({ ...current, state: "unavailable", detail: value.protocol ?? "" })); timer = setTimeout(check, pollIntervalMs); }
      }).catch(error => {
        if (!active) return;
        setHealth(current => ({ ...current, state: "unavailable", detail: formatApiError(error, "Review API") }));
        timer = setTimeout(check, pollIntervalMs);
      });
    };
    check();
    return () => { active = false; clearTimeout(timer); };
  }, [api, pollIntervalMs]);
  return health;
}

const tone = { ready: "border-success/40 text-success", checking: "border-info/40 text-info", unavailable: "border-destructive/40 text-destructive" } as const;

export function ApiStatus({ health }: { health: ApiHealth }) {
  const label = health.state === "ready" ? "Review API ready" : health.state === "checking" ? "Checking Review API" : "Review API unavailable";
  return <Badge variant="outline" className={cn("api-status", tone[health.state])} role="status" aria-live="polite" title={health.detail}>{label}</Badge>;
}
