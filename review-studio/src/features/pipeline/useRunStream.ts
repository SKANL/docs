import { useEffect, useState } from "react";
import { isTerminalStatus } from "@/api/domains/pipeline";
import { useApi } from "@/app/providers";

export type RunStream = { status?: string; percent?: number; message?: string; terminal: boolean; error?: string };
type Tagged = RunStream & { runId: string; workspaceId: string | null };

const BACKOFF_CAP_MS = 8_000;
const sleep = (ms: number, signal: AbortSignal) => new Promise<void>(resolve => {
  const timer = setTimeout(resolve, ms);
  signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
});

/**
 * Live progress for one run. Each (run, workspace) pair owns one AbortController: changing either, or unmounting,
 * aborts the stream. State is tagged with the pair that produced it, so a late event from an aborted stream can
 * neither be written (the closure checks its own signal) nor shown (the tag no longer matches the current run).
 */
export function useRunStream(runId: string | undefined, { workspaceId = null, backoffMs = 500, enabled = true }: { workspaceId?: string | null; backoffMs?: number; enabled?: boolean } = {}): RunStream {
  const api = useApi();
  const [state, setState] = useState<Tagged | null>(null);

  useEffect(() => {
    if (!runId || !enabled || !api.streamProgress) return;
    const controller = new AbortController();
    const { signal } = controller;
    const update = (patch: Partial<RunStream>) => {
      if (signal.aborted) return;
      setState(previous => ({ ...(previous && previous.runId === runId && previous.workspaceId === workspaceId ? previous : { terminal: false }), ...patch, runId, workspaceId } as Tagged));
    };
    let done = false;
    void (async () => {
      let delay = backoffMs;
      while (!signal.aborted && !done) {
        try {
          await api.streamProgress!(runId, event => {
            if (signal.aborted || (event.run?.id !== undefined && event.run.id !== runId)) return;
            const status = event.run?.status;
            const terminal = event.type === "terminal" || isTerminalStatus(status);
            if (terminal) done = true;
            update({ ...(status ? { status } : {}), ...(typeof event.progress === "number" ? { percent: event.progress } : {}), ...(event.message ? { message: event.message } : {}), ...(terminal ? { terminal: true } : {}), error: undefined });
          }, signal);
          delay = backoffMs;
        } catch (error) {
          if (signal.aborted) return;
          update({ error: error instanceof Error ? error.message : String(error) });
        }
        // The server closes a long stream before the run ends; reconnect with a growing pause until terminal.
        if (!done) { await sleep(delay, signal); delay = Math.min(delay * 2, BACKOFF_CAP_MS); }
      }
    })();
    return () => controller.abort();
  }, [api, runId, workspaceId, enabled, backoffMs]);

  return state && state.runId === runId && state.workspaceId === workspaceId ? { ...state, terminal: !!state.terminal } : { terminal: false };
}
