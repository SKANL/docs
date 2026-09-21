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
  Workspace,
  ImportResult,
  DocumentRecord,
  DocumentSection,
  DocumentContextTopic,
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
  accessToken?: string;
  fetch?: typeof globalThis.fetch;
  timeoutMs?: number;
  allowedPreviewOrigins?: readonly string[];
};

export type ListParams = { cursor?: string; limit?: number; workspaceId?: string };

const DEFAULT_TIMEOUT_MS = 15_000;
const STARTUP_RETRY_DELAYS_MS = [250, 500, 1_000, 2_000];

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

function normalizeArtifactKind(value: unknown): Artifact["kind"] {
  const kind = typeof value === "string" ? value.toUpperCase() : "";
  if (kind.includes("PDF")) return "PDF";
  if (kind.includes("HTML")) return "HTML";
  if (kind.includes("PNG") || kind.includes("PREVIEW")) return "PNG";
  return "DOCX";
}

function normalizeRun(raw: Record<string, unknown>): Run {
  if ((typeof raw.document === "string" && typeof raw.startedAt === "string") ||
      (Object.keys(raw).every(key => ["id", "schema"].includes(key)) && typeof raw.id === "string")) {
    return raw as unknown as Run;
  }
  const payload = raw.payload && typeof raw.payload === "object" ? raw.payload as Record<string, unknown> : {};
  const status = String(raw.status ?? "unverified") as Run["status"];
  const createdAt = String(raw.created_at ?? "");
  const started = typeof payload.started_at === "string" ? payload.started_at : createdAt;
  const progress = payload.progress && typeof payload.progress === "object" ? payload.progress as Record<string, unknown> : {};
  const results = payload.report && typeof payload.report === "object" ? (payload.report as Record<string, unknown>).execution : undefined;
  const execution = results && typeof results === "object" ? results as Record<string, unknown> : {};
  const stages = Array.isArray(execution.results) ? execution.results as Array<Record<string, unknown>> : [];
  const findings = typeof payload.findings === "number" ? payload.findings : stages.reduce((count, stage) => count + (Array.isArray(stage.errors) ? stage.errors.length : 0) + (Array.isArray(stage.warnings) ? stage.warnings.length : 0), 0);
  return {
    id: String(raw.id ?? ""),
    document: String(payload.document_id ?? "—"),
    template: String(payload.template ?? "—"),
    startedAt: started,
    duration: typeof payload.duration_ms === "number" ? `${payload.duration_ms} ms` : "—",
    status: ["passed", "succeeded", "warnings", "failed", "unverified", "queued", "running", "cancelled", "expired"].includes(status) ? status : "unverified",
    findings,
    artifactCount: typeof payload.artifact_count === "number" ? payload.artifact_count : stages.reduce((count, stage) => count + (Array.isArray(stage.artifacts) ? stage.artifacts.length : 0), 0),
    progress: typeof progress.percent === "number" ? progress.percent : undefined,
  };
}

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
  private readonly accessToken?: string;
  private readonly allowedPreviewOrigins: Set<string>;
  private selectedWorkspaceId?: string;

  constructor(options: ReviewClientOptions = {}) {
    this.baseUrl = new URL(options.baseUrl ?? "/v1", globalThis.location?.href ?? "http://localhost/").toString().replace(/\/$/, "");
    this.requestFetch = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.accessToken = options.accessToken?.trim() || undefined;
    this.allowedPreviewOrigins = new Set(options.allowedPreviewOrigins ?? []);
    try { this.selectedWorkspaceId = globalThis.localStorage?.getItem("docs.review.workspace") ?? undefined; } catch { this.selectedWorkspaceId = undefined; }
  }

  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    for (let attempt = 0; ; attempt += 1) {
      const request = withSignal(init.signal ?? undefined, this.timeoutMs);
      try {
        const response = await this.requestFetch(joinUrl(this.baseUrl, path), { ...init, signal: request.signal, headers: { Accept: "application/json", ...(this.accessToken ? { Authorization: `Bearer ${this.accessToken}` } : {}), ...init.headers } });
        if (!response.ok) throw await errorFromResponse(response);
        if (response.status === 204) return undefined as T;
        return await response.json() as T;
      } catch (error) {
        const retryable = error instanceof TypeError && !init.signal?.aborted && attempt < STARTUP_RETRY_DELAYS_MS.length;
        if (!retryable) throw error;
        await new Promise(resolve => globalThis.setTimeout(resolve, STARTUP_RETRY_DELAYS_MS[attempt]));
      } finally { request.cancel(); }
    }
  }

  private list<T>(path: string, params: ListParams = {}) {
    const query = new URLSearchParams();
    if (params.cursor) query.set("cursor", params.cursor);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    const workspaceId = params.workspaceId ?? this.selectedWorkspaceId;
    if (workspaceId) query.set("workspace_id", workspaceId);
    return this.request<unknown>(`${path}${query.size ? `?${query}` : ""}`).then(page<T>);
  }

  listRuns(params?: ListParams) { return this.list<Record<string, unknown>>("runs", params).then(result => result.items.map(normalizeRun)); }
  async health() {
    const response = await this.requestFetch(joinUrl(this.baseUrl, "../health"), { headers: { Accept: "application/json" } });
    if (!response.ok) throw new ApiError(`Review API health check failed (${response.status})`, response.status, "health_check_failed");
    return await response.json() as { ready:boolean; protocol?:string; version?:string };
  }
  listDocuments(params?: ListParams) { return this.list<DocumentRecord>("documents", params).then(result => result.items); }
  listFindings(params?: ListParams) { return this.list<Finding>("findings", params).then(result => result.items); }
  listArtifacts(params?: ListParams) {
    return this.list<Record<string, unknown>>("artifacts", params).then(result => result.items.map(raw => ({
        id: typeof raw.id === "string" ? raw.id : "artifact",
        name: typeof raw.name === "string" ? raw.name : typeof raw.id === "string" ? raw.id : "Unnamed artifact",
        runId: typeof raw.run_id === "string" ? raw.run_id : undefined,
        kind: normalizeArtifactKind(raw.kind),
        size: typeof raw.size === "string" ? raw.size : typeof raw.size === "number" ? `${raw.size} bytes` : "Size unavailable",
        status: raw.status === "failed" || raw.status === "warnings" || raw.status === "passed" ? raw.status : "unverified",
        pages: typeof raw.pages === "number" ? raw.pages : undefined,
        checksum: typeof raw.checksum === "string" ? raw.checksum : typeof raw.digest === "string" ? raw.digest : "Hash unavailable",
      } satisfies Artifact)));
  }
  getArtifact(id:string) { return this.request<Record<string, unknown>>("artifacts/" + encodeURIComponent(id)); }
  listArtifactPreviews(id:string) { return this.list<Record<string, unknown>>("artifacts/" + encodeURIComponent(id) + "/previews").then(result => result.items); }
  getPassport(runId: string) { return this.request<any>(`runs/${encodeURIComponent(runId)}/passport`).then(raw => { if (typeof raw?.coverage === "number") return raw as EvidencePassport; const entries=Array.isArray(raw?.entries)?raw.entries:[]; const pipeline=entries.find((entry:any)=>entry?.stage==="pipeline")?.result??{}; const execution=pipeline?.report?.execution; const results=Array.isArray(execution?.results)?execution.results:[]; const failures=results.filter((item:any)=>item?.ok===false).length; return {...raw,id:raw.run_id,runId:raw.run_id,verifiedAt:new Date().toISOString(),coverage:results.length?Math.round(((results.length-failures)/results.length)*100):0,attestations:entries.length,sources:0,claims:0,unresolved:failures,entries} as EvidencePassport; }); }
  getGraph() { const query = this.selectedWorkspaceId ? `?workspace_id=${encodeURIComponent(this.selectedWorkspaceId)}` : ""; return this.request<unknown>(`graph${query}`).then(normalizeGraph); }
  getGraphQuery(query: GraphQuery, id?: string) {
    const params = new URLSearchParams({ query });
    if (id) params.set("id", id);
    if (this.selectedWorkspaceId) params.set("workspace_id", this.selectedWorkspaceId);
    return this.request<unknown>(`graph?${params}`).then(normalizeGraphQuery);
  }
  listTemplates(params?: ListParams) { return this.list<Template>("templates", params).then(result => result.items); }
  listPlugins(params?: ListParams) { return this.list<Record<string, unknown>>("plugins", params).then(result => result.items); }
  listBaselines(params?: ListParams) { return this.list<Baseline>("baselines", params).then(result => result.items); }
  promoteBaseline(id:string) { return this.request<Record<string, unknown>>("baselines/promotions", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({baseline_id:id, ...(this.selectedWorkspaceId ? {workspace_id:this.selectedWorkspaceId} : {})}) }); }
  listRevisions(params?: ListParams) { return this.list<Revision>("revisions", params).then(result => result.items); }
  getRevision(id:string) { return this.request<Record<string, unknown>>("revisions/" + encodeURIComponent(id)); }
  listPublications(params?: ListParams) { return this.list<Publication>("publications", params).then(result => result.items); }
  listWorkspaces() {
    return this.request<unknown>("workspaces").then(raw => {
      const items = page<Workspace>(raw).items;
      const active = raw && typeof raw === "object" && "active" in raw ? (raw as { active?: Workspace }).active : undefined;
      const persisted = this.selectedWorkspaceId && items.some(item => item.id === this.selectedWorkspaceId) ? this.selectedWorkspaceId : undefined;
      const selected = persisted ?? active?.id ?? items[0]?.id;
      if (selected) {
        this.selectedWorkspaceId = selected;
        try { globalThis.localStorage?.setItem("docs.review.workspace", selected); } catch { /* offline/browser storage unavailable */ }
      }
      const selectedItem = selected ? items.find(item => item.id === selected) : undefined;
      return selectedItem ? [selectedItem, ...items.filter(item => item.id !== selected)] : items;
    });
  }
  createWorkspace(input: { name:string; root:string }) { return this.request<Workspace>("workspaces", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(input) }); }
  renameWorkspace(id:string,name:string) { return this.request<Workspace>("workspaces/"+encodeURIComponent(id), { method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify({name}) }); }
  async deleteWorkspace(id:string) {
    const result = await this.request<Record<string,unknown>>("workspaces/"+encodeURIComponent(id), { method:"DELETE" });
    if (this.selectedWorkspaceId === id) {
      this.selectedWorkspaceId = undefined;
      try { globalThis.localStorage?.removeItem("docs.review.workspace"); } catch { /* offline/browser storage unavailable */ }
    }
    return result;
  }
  getDocumentStatus(documentId:string,workspaceId?:string) { const query=workspaceId?"?workspace_id="+encodeURIComponent(workspaceId):""; return this.request<Record<string,unknown>>("documents/"+encodeURIComponent(documentId)+"/status"+query); }
  getDocumentContext(documentId:string) { return this.request<{document_id:string;topics:DocumentContextTopic[]}>("documents/"+encodeURIComponent(documentId)+"/context"); }
  getDocumentClassification(documentId:string) { return this.request<{document_id:string;items:Array<Record<string,unknown>>}>("documents/"+encodeURIComponent(documentId)+"/classification"); }
  confirmDocumentClassification(documentId:string,input:{relative_path:string;confirmed_role:"evidence"|"example"|"normative"}) { return this.request<Record<string,unknown>>("documents/"+encodeURIComponent(documentId)+"/classification", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(input) }); }
  setDocumentContext(documentId:string,input:{topic:string;field?:string;value:string}) { return this.request<Record<string,unknown>>("documents/"+encodeURIComponent(documentId)+"/context", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(input) }); }
  reviseDocument(documentId:string,input:{target_id:string;new_body?:string;new_value?:string;request?:string;field?:string}) { return this.request<Record<string,unknown>>("documents/"+encodeURIComponent(documentId)+"/revisions", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(input) }); }
  listDocumentSections(documentId:string) { return this.request<{items:DocumentSection[]}>("documents/"+encodeURIComponent(documentId)+"/sections").then(result=>result.items); }
  getDocumentSection(documentId:string,sectionId:string) { return this.request<DocumentSection>("documents/"+encodeURIComponent(documentId)+"/sections/"+encodeURIComponent(sectionId)); }
  updateDocumentSection(documentId:string,sectionId:string,body:string,request="Review Studio section edit") { return this.request<Record<string,unknown>>("documents/"+encodeURIComponent(documentId)+"/sections/"+encodeURIComponent(sectionId), { method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify({body,request}) }); }
  createDocument(input: { workspaceId:string; documentId:string; template:string; title?:string }) { return this.request<Record<string,unknown>>("documents", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({workspace_id:input.workspaceId,document_id:input.documentId,template:input.template,title:input.title??""}) }); }
  createRun(input: { documentId:string; workspaceId?:string; pipelineId?:string; format?:string }) { return this.request<Record<string,unknown>>("runs", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({document_id:input.documentId,workspace_id:input.workspaceId,pipeline_id:input.pipelineId??"document",format:input.format??"docx"}) }); }
  cancelRun(id:string) { return this.request<Record<string,unknown>>("runs/"+encodeURIComponent(id)+"/cancel", { method:"POST" }); }
  retryRun(id:string) { return this.request<Record<string,unknown>>("runs/"+encodeURIComponent(id)+"/retry", { method:"POST" }); }
  documentAction(documentId:string, action:"prepare"|"build"|"verify"|"publish", workspaceId:string, format="docx") { return this.request<Record<string,unknown>>("documents/"+encodeURIComponent(documentId)+"/"+action, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({workspace_id:workspaceId, policy: action === "publish" ? "release" : undefined, format}) }); }
  async selectWorkspace(id:string) {
    const workspace = await this.request<Workspace>("workspaces/" + encodeURIComponent(id) + "/select", { method:"POST" });
    this.selectedWorkspaceId = workspace.id;
    try { globalThis.localStorage?.setItem("docs.review.workspace", workspace.id); } catch { /* offline/browser storage unavailable */ }
    return workspace;
  }
  async importDocument(file: File, workspace: Workspace, options: {documentId?:string;template?:string;title?:string} = {}): Promise<ImportResult> {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const query = new URLSearchParams({workspace_id:workspace.id, template:options.template??"documento-generico", title:options.title??file.name});
    if (options.documentId) query.set("document_id", options.documentId);
    return this.request<ImportResult>("documents/import/raw?" + query.toString(), { method:"POST", headers:{"Content-Type":file.type||"application/octet-stream", "X-Docs-Filename":file.name}, body:bytes });
  }

  previewUrl(value: string): string {
    const url = new URL(value, `${this.baseUrl}/`);
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new TypeError("Preview URL must use HTTP(S)");
    const sameOrigin = url.origin === new URL(this.baseUrl).origin;
    if (!sameOrigin && !this.allowedPreviewOrigins.has(url.origin)) throw new TypeError("Preview URL origin is not allowed");
    return url.toString();
  }

  async streamProgress(runId: string, onEvent: (event: ProgressEvent) => void, signal?: AbortSignal): Promise<void> {
    let terminal = false;
    while (!terminal) {
      if (signal?.aborted) return;
      const request = withSignal(signal, this.timeoutMs);
      try {
        const response = await this.requestFetch(joinUrl(this.baseUrl, `runs/${encodeURIComponent(runId)}/progress`), { signal: request.signal, headers: { Accept: "text/event-stream" } });
        if (!response.ok) throw await errorFromResponse(response);
        if (!response.body) throw new ApiError("Progress stream has no body", 502, "empty_stream");
        await yieldSse(response.body, event => {
          onEvent(event);
          const status = (event.run as { status?: string } | undefined)?.status;
          terminal = ["succeeded", "completed", "failed", "cancelled", "expired"].includes(String(status));
        });
      } finally { request.cancel(); }
      if (!terminal) await waitForProgress(signal, 750);
    }
  }

  artifactPreviewUrl(runId: string, artifactId: string): string {
    return this.previewUrl(`runs/${encodeURIComponent(runId)}/previews/${encodeURIComponent(artifactId)}`);
  }
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
        const data = record.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
        if (!data || data === "[DONE]") continue;
        try { onEvent(JSON.parse(data) as ProgressEvent); } catch { /* Ignore malformed keep-alive records. */ }
      }
    }
    buffer += decoder.decode();
  } finally { reader.releaseLock(); }
}
