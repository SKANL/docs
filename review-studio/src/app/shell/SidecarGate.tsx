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

/** Desktop only: shows a startup screen while the local service boots and a failure screen (Retry, View log) if it does not. In a browser it renders the app directly. */
export function SidecarGate({ children, pollIntervalMs = 500 }: { children: ReactNode; pollIntervalMs?: number }) {
  const desktop = inTauri();
  const [phase, setPhase] = useState<Phase>(desktop ? "booting" : "ready");
  const failures = useRef(0);

  useEffect(() => {
    if (phase !== "booting" || !desktop) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = () => {
      invoke<Health>("sidecar_health").then(health => {
        if (!active) return;
        if (health.ready) return setPhase("ready");
        failures.current = health.state === "failed" ? failures.current + 1 : 0;
        if (failures.current >= CONFIRM_FAILURES) return setPhase("failed");
        timer = setTimeout(poll, pollIntervalMs);
      }).catch(() => { if (active) timer = setTimeout(poll, pollIntervalMs); });
    };
    poll();
    return () => { active = false; clearTimeout(timer); };
  }, [phase, desktop, pollIntervalMs]);

  const retry = useCallback(() => {
    failures.current = 0;
    setPhase("booting");
    // The restart command blocks until the service is healthy or has failed.
    invoke<Health>("sidecar_restart").then(() => setPhase("ready"), () => setPhase("failed"));
  }, []);

  if (phase === "ready") return <>{children}</>;
  return phase === "failed" ? <FailureScreen onRetry={retry} /> : <StartupScreen />;
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

function FailureScreen({ onRetry }: { onRetry(): void }) {
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
    </div>
    <div className="flex gap-3">
      <Button type="button" onClick={onRetry}>{t("sidecar.retry")}</Button>
      <Button type="button" variant="outline" onClick={toggleLog}>{t("sidecar.viewLog")}</Button>
    </div>
    {log !== undefined && <pre aria-label={t("sidecar.log")} className="max-h-72 overflow-auto rounded-md border bg-card p-3 text-xs whitespace-pre-wrap">{log}</pre>}
  </main>;
}
