import { ApiError } from "@/api/errors";
import type { MessageKey } from "@/lib/i18n";

export type ErrorKind = "network" | "auth" | "notFound" | "conflict" | "validation" | "server" | "unknown";

const STALE_CHUNK = /dynamically imported module|importing a module script/i;

/** HTTP status -> kind; first matching row wins. */
const STATUS_KINDS: ReadonlyArray<[(status: number) => boolean, ErrorKind]> = [
  [status => status === 0, "network"],
  [status => status === 401 || status === 403, "auth"],
  [status => status === 404, "notFound"],
  [status => status === 409, "conflict"],
  [status => status === 400 || status === 422, "validation"],
  [status => status >= 500, "server"],
];

/** Which plain-language message an error gets: by HTTP status family, or "network" when no response ever came back. */
export function errorKind(error: unknown): ErrorKind {
  if (error instanceof ApiError) {
    return STATUS_KINDS.find(([matches]) => matches(error.status))?.[1] ?? "unknown";
  }
  // A stale lazy chunk is a TypeError too (after a deploy), but the service is fine, so it is not "network".
  // It gets the generic message; RouteErrorBoundary adds the Reload button that actually fixes it.
  if (error instanceof TypeError && STALE_CHUNK.test(error.message)) return "unknown";
  // fetch rejects with a TypeError when the service cannot be reached; a timeout is a DOMException.
  if (error instanceof TypeError || (error instanceof DOMException && (error.name === "TimeoutError" || error.name === "NetworkError"))) return "network";
  return "unknown";
}

export const errorMessageKey = (error: unknown): MessageKey => `error.${errorKind(error)}`;

export type DetailField = "message" | "code" | "status" | "requestId";

/** What support needs: the raw server text, code, status and request id. Never the headline. */
export function technicalDetails(error: unknown): Array<[DetailField, string]> {
  if (error instanceof ApiError) return [["message", error.message], ["code", error.code], ["status", String(error.status)], ...(error.requestId ? [["requestId", error.requestId] as [DetailField, string]] : [])];
  return [["message", error instanceof Error ? error.message : String(error)]];
}
