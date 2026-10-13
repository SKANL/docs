// Typed client for the pipeline routes: plan, run, and the paged run list (S3.1 contract).
import type { ScopedRequest } from "./authoring";

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

export const TERMINAL_RUN_STATUSES = ["succeeded", "completed", "failed", "cancelled", "expired"];
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
}

const post = (body: Record<string, unknown>): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
/** JSON drops undefined values, so unchosen fields never reach the server. */
const defined = (input: Record<string, unknown>) => Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));

export function createPipelineApi(request: ScopedRequest): PipelineApi {
  const doc = (id: string) => `documents/${encodeURIComponent(id)}`;
  return {
    planPipeline: (id, { pipelineId, format } = {}) => request(`${doc(id)}/plan`, post(defined({ pipeline_id: pipelineId, format }))),
    runDocument: (id, { pipelineId, format, policy, strict, release } = {}) => request(`${doc(id)}/run`, post(defined({ pipeline_id: pipelineId, format, policy, strict, release }))),
    async listRunPage({ status, documentId, limit, cursor } = {}) {
      const query = new URLSearchParams();
      if (status) query.set("status", status);
      if (documentId) query.set("document_id", documentId);
      if (limit !== undefined) query.set("limit", String(limit));
      if (cursor) query.set("cursor", cursor);
      const raw = await request<{ items?: Array<Record<string, unknown>>; next_cursor?: unknown }>(`runs${query.size ? `?${query}` : ""}`);
      return { items: (raw.items ?? []).map(toRunRecord), nextCursor: typeof raw.next_cursor === "string" ? raw.next_cursor : undefined };
    },
  };
}
