import type {
  Artifact,
  Baseline,
  EvidencePassport,
  Finding,
  GraphQuery,
  GraphQueryItem,
  GraphQueryResult,
  GraphEdge,
  GraphNode,
  Publication,
  Revision,
  Run,
  Template,
} from "./models";

export type Page<T> = { items: T[]; nextCursor?: string; total?: number };
export type ProgressEvent = { type: string; progress?: number; message?: string; [key: string]: unknown };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;
  readonly requestId?: string;

  constructor(message: string, status: number, code = "api_error", details?: unknown, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export class ApiConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiConfigurationError";
  }
}

export function formatApiError(error: unknown, resource: string): string {
  if (error instanceof ApiError) {
    const summary = error.status === 401
      ? `Authentication required to load ${resource}.`
      : error.status === 403
        ? `You are not authorized to load ${resource}.`
        : `Unable to load ${resource}.`;
    const request = error.requestId ? ` Request ID: ${error.requestId}.` : "";
    return `${summary} ${error.message}${request}`;
  }
  if (error instanceof ApiConfigurationError) return error.message;
  return `Unable to load ${resource}. ${error instanceof Error ? error.message : "The API returned an unknown error."}`;
}

export type ReviewClientOptions = {
  baseUrl?: string;
  fetch?: typeof globalThis.fetch;
  timeoutMs?: number;
  allowedPreviewOrigins?: readonly string[];
};

export type ListParams = { cursor?: string; limit?: number };

const DEFAULT_TIMEOUT_MS = 15_000;

function joinUrl(baseUrl: string, path: string): URL {
  return new URL(path.replace(/^\/+/, ""), baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
}

function withSignal(signal: AbortSignal | undefined, timeoutMs: number): { signal: AbortSignal; cancel: () => void } {
  const controller = new AbortController();
  const timer = globalThis.setTimeout(() => controller.abort(new DOMException("Request timed out", "TimeoutError")), timeoutMs);
  const abort = () => controller.abort(signal?.reason ?? new DOMException("Request aborted", "AbortError"));
  if (signal) {
    if (signal.aborted) abort();
    else signal.addEventListener("abort", abort, { once: true });
  }
  return { signal: controller.signal, cancel: () => { clearTimeout(timer); signal?.removeEventListener("abort", abort); } };
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let payload: unknown;
  try { payload = await response.clone().json(); } catch { payload = await response.text().catch(() => undefined); }
  const body = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
  const message = typeof body.message === "string" ? body.message : typeof payload === "string" && payload ? payload : response.statusText || "Request failed";
  return new ApiError(message, response.status, typeof body.code === "string" ? body.code : "api_error", body.details, response.headers.get("x-request-id") ?? undefined);
}

function page<T>(payload: unknown): Page<T> {
  if (Array.isArray(payload)) return { items: payload as T[] };
  const value = payload as { items?: unknown; data?: unknown; next_cursor?: unknown; nextCursor?: unknown; total?: unknown };
  const items = Array.isArray(value?.items) ? value.items : Array.isArray(value?.data) ? value.data : [];
  return { items: items as T[], nextCursor: typeof value?.nextCursor === "string" ? value.nextCursor : typeof value?.next_cursor === "string" ? value.next_cursor : undefined, total: typeof value?.total === "number" ? value.total : undefined };
}

type RawGraphNode = { id?: unknown; kind?: unknown; label?: unknown; confidence?: unknown; attributes?: unknown; x?: unknown; y?: unknown };
type RawGraphEdge = { source?: unknown; target?: unknown; relation?: unknown; from?: unknown; to?: unknown };

const graphType = (kind: string): GraphNode["type"] => {
  if (kind === "claim" || kind === "artifact" || kind === "section" || kind === "source") return kind;
  return kind === "evidence" || kind === "input" || kind === "reference" ? "source" : "claim";
};

const confidenceScore = (value: unknown): number => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (value && typeof value === "object" && typeof (value as { score?: unknown }).score === "number") return (value as { score: number }).score;
  return 0;
};

function normalizeGraph(payload: unknown): { nodes:GraphNode[]; edges:GraphEdge[] } {
  const value = payload && typeof payload === "object" ? payload as { nodes?: unknown; edges?: unknown } : {};
  const rawNodes = Array.isArray(value.nodes) ? value.nodes as RawGraphNode[] : [];
  const nodes = rawNodes.flatMap((node, index) => {
    if (typeof node.id !== "string") return [];
    const angle = rawNodes.length ? (index / rawNodes.length) * Math.PI * 2 : 0;
    return [{ id:node.id, label:typeof node.label === "string" ? node.label : node.id, type:graphType(typeof node.kind === "string" ? node.kind : "entity"), confidence:confidenceScore(node.confidence), x:typeof node.x === "number" ? node.x : 50 + Math.cos(angle) * 32, y:typeof node.y === "number" ? node.y : 50 + Math.sin(angle) * 32 }];
  });
  const edges = (Array.isArray(value.edges) ? value.edges as RawGraphEdge[] : []).flatMap(edge => {
    const from = typeof edge.source === "string" ? edge.source : edge.from;
    const to = typeof edge.target === "string" ? edge.target : edge.to;
    return typeof from === "string" && typeof to === "string" ? [{ from, to, relation:typeof edge.relation === "string" ? edge.relation : "related" }] : [];
  });
  return { nodes, edges };
}

function normalizeGraphQuery(payload: unknown): GraphQueryResult {
  const value = payload && typeof payload === "object" ? payload as { items?: unknown; graph_unavailable?: unknown; warnings?: unknown; context?: unknown } : {};
  const items = (Array.isArray(value.items) ? value.items : []).flatMap((item): GraphQueryItem[] => {
    if (!item || typeof item !== "object") return [];
    const candidate = item as Record<string, unknown>;
    if (typeof candidate.id !== "string") return [];
    const attributes = candidate.attributes && typeof candidate.attributes === "object" ? candidate.attributes as Record<string, unknown> : undefined;
    return [{ id:candidate.id, kind:typeof candidate.kind === "string" ? candidate.kind : "entity", label:typeof candidate.label === "string" ? candidate.label : candidate.id, confidence:confidenceScore(candidate.confidence), attributes }];
  });
  return { items, graphUnavailable:value.graph_unavailable === true, warnings:Array.isArray(value.warnings) ? value.warnings.filter((warning): warning is string => typeof warning === "string") : undefined, context:value.context && typeof value.context === "object" ? value.context as Record<string, unknown> : undefined };
}

export class ReviewApiClient {
  readonly baseUrl: string;
  private readonly requestFetch: typeof globalThis.fetch;
  private readonly timeoutMs: number;
  private readonly allowedPreviewOrigins: Set<string>;

  constructor(options: ReviewClientOptions = {}) {
    this.baseUrl = new URL(options.baseUrl ?? "/v1", globalThis.location?.href ?? "http://localhost/").toString().replace(/\/$/, "");
    this.requestFetch = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.allowedPreviewOrigins = new Set(options.allowedPreviewOrigins ?? []);
  }

  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const request = withSignal(init.signal ?? undefined, this.timeoutMs);
    try {
      const response = await this.requestFetch(joinUrl(this.baseUrl, path), { ...init, signal: request.signal, headers: { Accept: "application/json", ...init.headers } });
      if (!response.ok) throw await errorFromResponse(response);
      if (response.status === 204) return undefined as T;
      return await response.json() as T;
    } finally { request.cancel(); }
  }

  private list<T>(path: string, params: ListParams = {}) {
    const query = new URLSearchParams();
    if (params.cursor) query.set("cursor", params.cursor);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    return this.request<unknown>(`${path}${query.size ? `?${query}` : ""}`).then(page<T>);
  }

  listRuns(params?: ListParams) { return this.list<Run>("runs", params); }
  listFindings(params?: ListParams) { return this.list<Finding>("findings", params); }
  listArtifacts(params?: ListParams) { return this.list<Artifact>("artifacts", params); }
  getPassport(runId: string) { return this.request<EvidencePassport>(`runs/${encodeURIComponent(runId)}/passport`); }
  getGraph() { return this.request<unknown>("graph").then(normalizeGraph); }
  getGraphQuery(query: GraphQuery, id?: string) {
    const params = new URLSearchParams({ query });
    if (id) params.set("id", id);
    return this.request<unknown>(`graph?${params}`).then(normalizeGraphQuery);
  }
  listTemplates(params?: ListParams) { return this.list<Template>("templates", params); }
  listBaselines(params?: ListParams) { return this.list<Baseline>("baselines", params); }
  listRevisions(params?: ListParams) { return this.list<Revision>("revisions", params); }
  listPublications(params?: ListParams) { return this.list<Publication>("publications", params); }

  previewUrl(value: string): string {
    const url = new URL(value, `${this.baseUrl}/`);
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new TypeError("Preview URL must use HTTP(S)");
    const sameOrigin = url.origin === new URL(this.baseUrl).origin;
    if (!sameOrigin && !this.allowedPreviewOrigins.has(url.origin)) throw new TypeError("Preview URL origin is not allowed");
    return url.toString();
  }

  async streamProgress(runId: string, onEvent: (event: ProgressEvent) => void, signal?: AbortSignal): Promise<void> {
    const request = withSignal(signal, this.timeoutMs);
    try {
      const response = await this.requestFetch(joinUrl(this.baseUrl, `runs/${encodeURIComponent(runId)}/progress`), { signal: request.signal, headers: { Accept: "text/event-stream" } });
      if (!response.ok) throw await errorFromResponse(response);
      if (!response.body) throw new ApiError("Progress stream has no body", 502, "empty_stream");
      await yieldSse(response.body, onEvent);
    } finally { request.cancel(); }
  }
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
        const data = record.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
        if (!data || data === "[DONE]") continue;
        try { onEvent(JSON.parse(data) as ProgressEvent); } catch { /* Ignore malformed keep-alive records. */ }
      }
    }
    buffer += decoder.decode();
  } finally { reader.releaseLock(); }
}
