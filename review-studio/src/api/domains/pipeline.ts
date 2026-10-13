// Typed client for the pipeline routes: plan, run, the paged run list, run actions and live progress (S3.1 contract).
import { ApiError } from "../errors";
import { defined, docPath, jsonInit, type Transport } from "../http";

export type OutputFormat = "docx" | "pdf" | "html";
export type RunPolicy = "draft" | "strict" | "release";

export interface PipelinePlan { document_id: string; pipeline_id: string; stages: string[]; external_artifacts: string[]; contracts: Array<Record<string, unknown>> }
export interface RunStarted {
  id: string; status: string; document_id: string; pipeline_id: string; format: string; policy: string;
  links: { self: string; progress: string; cancel: string };
}
export interface PlanInput { pipelineId?: string; format?: string }
export interface RunInput { pipelineId?: string; format?: string; policy?: RunPolicy; strict?: boolean; release?: boolean }
export interface RunFilters { status?: string; documentId?: string; limit?: number; cursor?: string }

/** A run reduced to what the UI shows; the raw payload never reaches a component. */
export interface RunRecord {
  id: string; status: string; documentId?: string; pipelineId?: string; format?: string; policy?: string;
  createdAt?: string; percent?: number; stage?: string; retryOf?: string;
}
export interface RunPage { items: RunRecord[]; nextCursor?: string }

/** One decoded server-sent progress event. `run` is present on frames that carry the run's current state. */
export type ProgressEvent = { type: string; progress?: number; message?: string; run?: { id?: string; status?: string }; [key: string]: unknown };
export type DocumentAction = "prepare" | "build" | "verify" | "publish";

const TERMINAL_RUN_STATUSES = ["succeeded", "completed", "failed", "cancelled", "expired"];
export const isTerminalStatus = (status: string | undefined) => !!status && TERMINAL_RUN_STATUSES.includes(status);

const text = (value: unknown) => typeof value === "string" && value ? value : undefined;

export function toRunRecord(raw: Record<string, unknown>): RunRecord {
  const payload = raw.payload && typeof raw.payload === "object" ? raw.payload as Record<string, unknown> : {};
  const progress = payload.progress && typeof payload.progress === "object" ? payload.progress as Record<string, unknown> : {};
  return {
    id: String(raw.id ?? ""), status: String(raw.status ?? "unknown"),
    documentId: text(payload.document_id), pipelineId: text(payload.pipeline_id), format: text(payload.format), policy: text(payload.policy),
    createdAt: text(raw.created_at), percent: typeof progress.percent === "number" ? progress.percent : undefined,
    stage: text(progress.stage), retryOf: text(payload.retry_of),
  };
}

export interface PipelineApi {
  planPipeline(documentId: string, input?: PlanInput): Promise<PipelinePlan>;
  runDocument(documentId: string, input?: RunInput): Promise<RunStarted>;
  listRunPage(filters?: RunFilters): Promise<RunPage>;
  getRun(id: string): Promise<Record<string, unknown>>;
  cancelRun(id: string): Promise<Record<string, unknown>>;
  retryRun(id: string): Promise<Record<string, unknown>>;
  documentAction(documentId: string, action: DocumentAction, workspaceId: string, format?: string): Promise<Record<string, unknown>>;
  streamProgress(runId: string, onEvent: (event: ProgressEvent) => void, signal?: AbortSignal): Promise<void>;
}

export function createPipelineApi(t: Transport): PipelineApi {
  const request = t.scoped;
  const runPath = (id: string) => `runs/${encodeURIComponent(id)}`;
  return {
    planPipeline: (id, { pipelineId, format } = {}) => request(`${docPath(id)}/plan`, jsonInit("POST", defined({ pipeline_id: pipelineId, format }))),
    runDocument: (id, { pipelineId, format, policy, strict, release } = {}) => request(`${docPath(id)}/run`, jsonInit("POST", defined({ pipeline_id: pipelineId, format, policy, strict, release }))),
    async listRunPage({ status, documentId, limit, cursor } = {}) {
      const query = new URLSearchParams();
      if (status) query.set("status", status);
      if (documentId) query.set("document_id", documentId);
      if (limit !== undefined) query.set("limit", String(limit));
      if (cursor) query.set("cursor", cursor);
      const raw = await request<{ items?: Array<Record<string, unknown>>; next_cursor?: unknown }>(`runs${query.size ? `?${query}` : ""}`);
      return { items: (raw.items ?? []).map(toRunRecord), nextCursor: typeof raw.next_cursor === "string" ? raw.next_cursor : undefined };
    },
    getRun: id => request(runPath(id)),
    cancelRun: id => request(`${runPath(id)}/cancel`, jsonInit("POST")),
    retryRun: id => request(`${runPath(id)}/retry`, jsonInit("POST")),
    documentAction: (id, action, workspaceId, format = "docx") =>
      request(`${docPath(id)}/${action}`, jsonInit("POST", { workspace_id: workspaceId, policy: action === "publish" ? "release" : undefined, format }), workspaceId),
    async streamProgress(runId, onEvent, signal) {
      let terminal = false;
      while (!terminal) {
        if (signal?.aborted) return;
        const workspaceId = await t.workspaceId();
        await t.send(`${runPath(runId)}/progress?workspace_id=${encodeURIComponent(workspaceId)}`, { signal, headers: { Accept: "text/event-stream" } }, async response => {
          if (!response.body) throw new ApiError("Progress stream has no body", 502, "empty_stream");
          await yieldSse(response.body, event => {
            onEvent(event);
            terminal = event.type === "terminal" || isTerminalStatus(event.run?.status);
          });
        });
        if (!terminal) await waitForProgress(signal, 750);
      }
    },
  };
}

async function waitForProgress(signal: AbortSignal | undefined, delayMs: number): Promise<void> {
  await new Promise<void>(resolve => {
    const timer = globalThis.setTimeout(resolve, delayMs);
    signal?.addEventListener("abort", () => { globalThis.clearTimeout(timer); resolve(); }, { once: true });
  });
}

export async function yieldSse(stream: ReadableStream<Uint8Array>, onEvent: (event: ProgressEvent) => void): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const records = buffer.split(/\r?\n\r?\n/);
      buffer = records.pop() ?? "";
      for (const record of records) {
        const lines = record.split(/\r?\n/);
        const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
        if (!data || data === "[DONE]") continue;
        const name = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
        try {
          const event = JSON.parse(data) as ProgressEvent;
          // The server's closing frame is `event: terminal`; its payload carries no `type` of its own.
          onEvent(name === "terminal" ? { ...event, type: "terminal" } : event);
        } catch { /* Ignore malformed keep-alive records. */ }
      }
    }
    buffer += decoder.decode();
  } finally { reader.releaseLock(); }
}
