import { ApiConfigurationError, ApiError } from "./errors";
import { authHeaders, workspaceStorage, type Transport, type WorkspaceSession } from "./http";
import { createAuthoringApi, type AuthoringApi } from "./domains/authoring";
import { createDeliveryApi, type DeliveryApi } from "./domains/delivery";
import { createPipelineApi, type PipelineApi } from "./domains/pipeline";
import { createReviewDomainApi, type ReviewDomainApi } from "./domains/review";
import { createSystemApi, type SystemApi } from "./domains/system";
import { createTemplatesApi, type TemplatesApi } from "./domains/templates";
import { createToolsApi, type ToolsApi } from "./domains/tools";
import { createWorkspacesApi, type WorkspacesApi } from "./domains/workspaces";

export type ReviewClientOptions = {
  baseUrl?: string;
  accessToken?: string;
  fetch?: typeof globalThis.fetch;
  timeoutMs?: number;
  allowedPreviewOrigins?: readonly string[];
};

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
  const raw = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
  // The server wraps failures as { error: { code, message, details } }.
  const body = raw.error && typeof raw.error === "object" ? raw.error as Record<string, unknown> : raw;
  const message = typeof body.message === "string" ? body.message : typeof payload === "string" && payload ? payload : response.statusText || "Request failed";
  return new ApiError(message, response.status, typeof body.code === "string" ? body.code : "api_error", body.details, response.headers.get("x-request-id") ?? undefined);
}

/** The one HTTP client. Every operation lives in a domain; this class only owns transport, auth and the selected workspace. */
export class ReviewApiClient {
  readonly baseUrl: string;
  /** Health and the capability catalogue. */
  readonly system: SystemApi;
  /** Workspaces, documents and source import. */
  readonly workspaces: WorkspacesApi;
  /** Source, asset, classification, context, section and revision operations. */
  readonly authoring: AuthoringApi;
  /** Plan, run, run list and live progress. */
  readonly pipeline: PipelineApi;
  /** Findings, artifacts, evidence, baselines, graph, inspect, diff, qa-docx and corrections. */
  readonly review: ReviewDomainApi;
  /** Package, publish and the publication history. */
  readonly delivery: DeliveryApi;
  /** Template administration and the plugin registry. */
  readonly templates: TemplatesApi;
  /** Specialist tools, diagnostics, issue codes and translation download. */
  readonly tools: ToolsApi;
  private readonly requestFetch: typeof globalThis.fetch;
  private readonly timeoutMs: number;
  private readonly accessToken?: string;
  private readonly allowedPreviewOrigins: Set<string>;

  constructor(options: ReviewClientOptions = {}) {
    const configuredBase = new URL(options.baseUrl ?? "/v2", globalThis.location?.href ?? "http://localhost/");
    const path = configuredBase.pathname.replace(/\/+$/, "");
    configuredBase.pathname = path.endsWith("/v2") ? path : `${path}/v2`;
    this.baseUrl = configuredBase.toString().replace(/\/$/, "");
    this.requestFetch = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.accessToken = options.accessToken?.trim() || undefined;
    this.allowedPreviewOrigins = new Set(options.allowedPreviewOrigins ?? []);

    const session: WorkspaceSession = { selected: workspaceStorage.read(), select(id) { this.selected = id; workspaceStorage.write(id); } };
    const transport: Transport = {
      request: (path, init = {}) => this.request(path, init),
      scoped: async (path, init = {}, explicitWorkspaceId) => {
        const workspaceId = await transport.workspaceId(explicitWorkspaceId);
        const [pathname, rawQuery] = path.split("?", 2);
        const query = new URLSearchParams(rawQuery ?? "");
        query.set("workspace_id", workspaceId);
        return this.request(`${pathname}?${query}`, init);
      },
      send: (path, init, read) => this.send(path, init, read),
      workspaceId: async explicit => {
        if (explicit) return explicit;
        if (!session.selected) await this.workspaces.listWorkspaces();
        if (!session.selected) throw new ApiConfigurationError("No workspace is available. Create a workspace before continuing.");
        return session.selected;
      },
      previewUrl: value => this.previewUrl(value),
      session,
    };
    this.system = createSystemApi(transport);
    this.workspaces = createWorkspacesApi(transport);
    this.authoring = createAuthoringApi(transport);
    this.pipeline = createPipelineApi(transport);
    this.review = createReviewDomainApi(transport);
    this.delivery = createDeliveryApi(transport);
    this.templates = createTemplatesApi(transport);
    this.tools = createToolsApi(transport);
  }

  /** One timed, authenticated request. The caller reads the body; a failed response throws an ApiError. */
  private async send<T>(path: string, init: RequestInit, read: (response: Response) => Promise<T>): Promise<T> {
    const request = withSignal(init.signal ?? undefined, this.timeoutMs);
    try {
      const response = await this.requestFetch(joinUrl(this.baseUrl, path), { ...init, signal: request.signal, headers: { ...authHeaders(this.accessToken), ...init.headers } });
      if (!response.ok) throw await errorFromResponse(response);
      return await read(response);
    } finally { request.cancel(); }
  }

  /** A JSON request that survives the sidecar's cold start: a refused connection is retried with a growing pause. */
  private async request<T>(path: string, init: RequestInit): Promise<T> {
    const withAccept = { ...init, headers: { Accept: "application/json", ...init.headers } };
    for (let attempt = 0; ; attempt += 1) {
      try {
        return await this.send(path, withAccept, async response => response.status === 204 ? undefined as T : await response.json() as T);
      } catch (error) {
        const retryable = error instanceof TypeError && !init.signal?.aborted && attempt < STARTUP_RETRY_DELAYS_MS.length;
        if (!retryable) throw error;
        await new Promise(resolve => globalThis.setTimeout(resolve, STARTUP_RETRY_DELAYS_MS[attempt]));
      }
    }
  }

  previewUrl(value: string): string {
    const url = new URL(value, `${this.baseUrl}/`);
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new TypeError("Preview URL must use HTTP(S)");
    const sameOrigin = url.origin === new URL(this.baseUrl).origin;
    if (!sameOrigin && !this.allowedPreviewOrigins.has(url.origin)) throw new TypeError("Preview URL origin is not allowed");
    return url.toString();
  }
}
