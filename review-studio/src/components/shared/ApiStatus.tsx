import { useEffect, useState } from "react";
import type { ReviewApi } from "@/api/models";
import { errorMessageKey, technicalDetails } from "@/lib/friendly-error";
import { useT } from "@/lib/i18n";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type ApiHealth = { state: "checking" | "ready" | "unavailable"; /** Protocol text, or "" */ detail: string; /** Why the service is unreachable, when a call failed. */ error?: unknown; readyEpoch: number };

/** Poll the service health until it is ready: the desktop sidecar cold-starts after the UI renders. */
export function useApiHealth(api: ReviewApi, pollIntervalMs = 2000): ApiHealth {
  const [health, setHealth] = useState<ApiHealth>({ state: "checking", detail: "", readyEpoch: 0 });
  useEffect(() => {
    if (!api.health) { setHealth(current => ({ ...current, state: "unavailable", detail: "", error: new Error("Health endpoint is not available") })); return; }
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = () => {
      api.health!().then(value => {
        if (!active) return;
        if (value.ready) setHealth(current => ({ state: "ready", detail: value.protocol ?? "", error: undefined, readyEpoch: current.state === "unavailable" ? current.readyEpoch + 1 : current.readyEpoch }));
        else { setHealth(current => ({ ...current, state: "unavailable", detail: value.protocol ?? "", error: undefined })); timer = setTimeout(check, pollIntervalMs); }
      }).catch(error => {
        if (!active) return;
        setHealth(current => ({ ...current, state: "unavailable", detail: "", error }));
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
  const { t } = useT();
  // The tooltip keeps the plain-language reason and the raw message for support.
  const detail = health.error === undefined ? health.detail : `${t(errorMessageKey(health.error))} (${technicalDetails(health.error)[0]![1]})`;
  return <Badge variant="outline" className={cn("api-status", tone[health.state])} role="status" aria-live="polite" title={detail}>{t(`api.${health.state}`)}</Badge>;
}
