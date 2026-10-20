import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

type Health = { ready: boolean; state: string };
type Phase = "booting" | "ready" | "failed";

const inTauri = () => typeof window !== "undefined" && typeof (window as unknown as { __TAURI_INTERNALS__?: { invoke?: unknown } }).__TAURI_INTERNALS__?.invoke === "function";
// Plain IPC call: avoids a direct @tauri-apps/api dependency for three commands.
const invoke = <T,>(command: string) => (window as unknown as { __TAURI_INTERNALS__: { invoke(command: string): Promise<T> } }).__TAURI_INTERNALS__.invoke(command);

/** Consecutive "failed" answers needed before the failure screen shows: the shell reports "failed" for a moment before it starts the service. */
const CONFIRM_FAILURES = 2;
/** How long the startup screen may wait before it gives up and offers Retry / View log. */
const STARTUP_TIMEOUT_MS = 120_000;
/** A restart that has not answered by then is treated as failed, so a hung shell call cannot pin the startup screen. */
const RESTART_TIMEOUT_MS = 120_000;
/** On the failure screen a slow service that turns healthy later is still noticed, at this slower pace. */
const RECOVERY_POLL_MS = 3_000;

/** Desktop only: shows a startup screen while the local service boots and a failure screen (Retry, View log) if it does not. In a browser it renders the app directly. */
export function SidecarGate({ children, pollIntervalMs = 500, startupTimeoutMs = STARTUP_TIMEOUT_MS, restartTimeoutMs = RESTART_TIMEOUT_MS, recoveryPollMs = RECOVERY_POLL_MS }: { children: ReactNode; pollIntervalMs?: number; startupTimeoutMs?: number; restartTimeoutMs?: number; recoveryPollMs?: number }) {
  const desktop = inTauri();
  const [phase, setPhase] = useState<Phase>(desktop ? "booting" : "ready");
  const [error, setError] = useState<string>();
  const failures = useRef(0);
  // While a restart is pending, its own answer is the only truth: health polls still see the old state.
  const restarting = useRef(false);

  useEffect(() => {
    if (phase !== "booting" || !desktop) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = () => {
      invoke<Health>("sidecar_health").then(health => {
        if (!active) return;
        if (!restarting.current) {
          if (health.ready) return setPhase("ready");
          failures.current = health.state === "failed" ? failures.current + 1 : 0;
          if (failures.current >= CONFIRM_FAILURES) return setPhase("failed");
        }
        timer = setTimeout(poll, pollIntervalMs);
      }).catch(() => { if (active) timer = setTimeout(poll, pollIntervalMs); });
    };
    poll();
    const giveUp = setTimeout(() => { if (active && !restarting.current) setPhase("failed"); }, startupTimeoutMs);
    return () => { active = false; clearTimeout(timer); clearTimeout(giveUp); };
  }, [phase, desktop, pollIntervalMs, startupTimeoutMs]);

  // After giving up (or a failed start) keep watching: a service that is merely slow can still come up, and Retry would restart it.
  useEffect(() => {
    if (phase !== "failed" || !desktop) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = () => {
      invoke<Health>("sidecar_health").then(health => {
        if (!active) return;
        if (health.ready) return setPhase("ready");
        timer = setTimeout(poll, recoveryPollMs);
      }).catch(() => { if (active) timer = setTimeout(poll, recoveryPollMs); });
    };
    timer = setTimeout(poll, recoveryPollMs);
    return () => { active = false; clearTimeout(timer); };
  }, [phase, desktop, recoveryPollMs]);

  const retry = useCallback(() => {
    failures.current = 0;
    restarting.current = true;
    setError(undefined);
    setPhase("booting");
    // The restart command blocks until the service is healthy or has failed; its answer decides.
    // Bounded: if the shell call never settles, the timeout ends the wait and a late answer is ignored.
    let done = false;
    const finish = (apply: () => void) => { if (done) return; done = true; clearTimeout(bound); restarting.current = false; apply(); };
    const bound = setTimeout(() => finish(() => { setError("sidecar restart timed out"); setPhase("failed"); }), restartTimeoutMs);
    invoke<Health>("sidecar_restart").then(
      health => finish(() => setPhase(health.ready ? "ready" : "failed")),
      reason => finish(() => { setError(String(reason)); setPhase("failed"); }),
    );
  }, [restartTimeoutMs]);

  if (phase === "ready") return <>{children}</>;
  return phase === "failed" ? <FailureScreen onRetry={retry} error={error} /> : <StartupScreen />;
}

const screenClass = "mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-4 px-6";

function StartupScreen() {
  const { t } = useT();
  return <main className={screenClass}>
    <div role="status" aria-live="polite" className="grid gap-2">
      <h1 className="text-2xl font-semibold">{t("sidecar.starting.title")}</h1>
      <p className="text-muted-foreground">{t("sidecar.starting.body")}</p>
    </div>
  </main>;
}

function FailureScreen({ onRetry, error }: { onRetry(): void; error?: string }) {
  const { t } = useT();
  const [log, setLog] = useState<string>();
  const toggleLog = async () => {
    try { const text = await invoke<string>("sidecar_log"); setLog(text.trim() || t("sidecar.logEmpty")); }
    catch (reason) { setLog(t("sidecar.logFailed", { error: String(reason) })); }
  };
  return <main className={screenClass}>
    <div role="alert" className="grid gap-2">
      <h1 className="text-2xl font-semibold">{t("sidecar.failed.title")}</h1>
      <p className="text-muted-foreground">{t("sidecar.failed.body")}</p>
      {error && <p className="text-sm break-words">{error}</p>}
    </div>
    <div className="flex gap-3">
      <Button type="button" onClick={onRetry}>{t("sidecar.retry")}</Button>
      <Button type="button" variant="outline" onClick={toggleLog}>{t("sidecar.viewLog")}</Button>
    </div>
    {log !== undefined && <pre aria-label={t("sidecar.log")} className="max-h-72 overflow-auto rounded-md border bg-card p-3 text-xs whitespace-pre-wrap">{log}</pre>}
  </main>;
}
