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

/**
 * The one way an error reaches the user. The server message is kept as-is (it already says what went wrong).
 * Pass `resource` for a headline that also names what could not be loaded and distinguishes 401 from 403.
 */
export function formatApiError(error: unknown, resource?: string): string {
  if (error instanceof ApiError) {
    const request = error.requestId ? ` Request ID: ${error.requestId}.` : "";
    if (!resource) return `${error.message}${request}`;
    const summary = error.status === 401
      ? `Authentication required to load ${resource}.`
      : error.status === 403
        ? `You are not authorized to load ${resource}.`
        : `Unable to load ${resource}.`;
    return `${summary} ${error.message}${request}`;
  }
  if (error instanceof ApiConfigurationError) return error.message;
  const detail = error instanceof Error ? error.message : "The API returned an unknown error.";
  return resource ? `Unable to load ${resource}. ${detail}` : detail;
}
