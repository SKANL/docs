import { ApiError } from "@/api/errors";
import type { MessageKey } from "@/lib/i18n";

export type ErrorKind = "network" | "auth" | "notFound" | "conflict" | "validation" | "server" | "unknown";

/** Which plain-language message an error gets: by HTTP status family, or "network" when no response ever came back. */
export function errorKind(error: unknown): ErrorKind {
  if (error instanceof ApiError) {
    const { status } = error;
    return status === 0 ? "network" : status === 401 || status === 403 ? "auth" : status === 404 ? "notFound" : status === 409 ? "conflict"
      : status === 400 || status === 422 ? "validation" : status >= 500 ? "server" : "unknown";
  }
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
