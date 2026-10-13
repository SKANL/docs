// Request helpers shared by every API domain.

/** Workspace-scoped request function supplied by the API client; `workspaceId` overrides the selected workspace. */
export type ScopedRequest = <T>(path: string, init?: RequestInit, workspaceId?: string) => Promise<T>;

/** The selected workspace, remembered across reloads. */
export interface WorkspaceSession { selected?: string; select(id: string | undefined): void }

/** What every domain is built on; the API client supplies it. */
export interface Transport {
  /** A workspace-scoped JSON request. */
  scoped: ScopedRequest;
  /** An unscoped JSON request (workspaces, capabilities). */
  request<T>(path: string, init?: RequestInit): Promise<T>;
  /** One timed, authenticated request whose body the caller reads (blob, stream). Failed responses throw an ApiError. */
  send<T>(path: string, init: RequestInit, read: (response: Response) => Promise<T>): Promise<T>;
  /** The workspace a request is scoped to; selects the first one when none is selected yet. */
  workspaceId(explicit?: string): Promise<string>;
  /** Validates a preview URL against the API origin and the allowed preview origins. */
  previewUrl(value: string): string;
  session: WorkspaceSession;
}

export type Page<T> = { items: T[]; nextCursor?: string; total?: number };
export type ListParams = { cursor?: string; limit?: number; workspaceId?: string };

/** A JSON request. A body-less call (GET/DELETE) sends no Content-Type. */
export const jsonInit = (method: string, body?: unknown): RequestInit =>
  ({ method, ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });

export const docPath = (id: string) => `documents/${encodeURIComponent(id)}`;

/** JSON drops undefined values, so unchosen fields never reach the server. */
export const defined = (input: Record<string, unknown>) => Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));

/** The one place the bearer header is built. */
export const authHeaders = (accessToken?: string): Record<string, string> => accessToken ? { Authorization: `Bearer ${accessToken}` } : {};

export function toPage<T>(payload: unknown): Page<T> {
  if (Array.isArray(payload)) return { items: payload as T[] };
  const value = payload as { items?: unknown; data?: unknown; next_cursor?: unknown; nextCursor?: unknown; total?: unknown };
  const items = Array.isArray(value?.items) ? value.items : Array.isArray(value?.data) ? value.data : [];
  return { items: items as T[], nextCursor: typeof value?.nextCursor === "string" ? value.nextCursor : typeof value?.next_cursor === "string" ? value.next_cursor : undefined, total: typeof value?.total === "number" ? value.total : undefined };
}

export function listPage<T>(request: ScopedRequest, path: string, params: ListParams = {}): Promise<Page<T>> {
  const query = new URLSearchParams();
  if (params.cursor) query.set("cursor", params.cursor);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  return request<unknown>(`${path}${query.size ? `?${query}` : ""}`, {}, params.workspaceId).then(toPage<T>);
}

const WORKSPACE_KEY = "docs.review.workspace";

/** The selected workspace, remembered on this device. Storage may be blocked; the app still works without it. */
export const workspaceStorage = {
  read(): string | undefined {
    try { return globalThis.localStorage?.getItem(WORKSPACE_KEY) ?? undefined; } catch { return undefined; }
  },
  write(id: string | undefined): void {
    try { if (id) globalThis.localStorage?.setItem(WORKSPACE_KEY, id); else globalThis.localStorage?.removeItem(WORKSPACE_KEY); } catch { /* browser storage unavailable */ }
  },
};
