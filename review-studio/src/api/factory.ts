import { ReviewApiClient } from "./client";
import { ApiConfigurationError } from "./errors";
import type { ReviewApi } from "./models";

export type ReviewApiEnvironment = {
  apiBaseUrl?: string;
  accessToken?: string;
  fetch?: typeof globalThis.fetch;
};

export function createReviewApi(environment: ReviewApiEnvironment = { apiBaseUrl: import.meta.env.VITE_DOCS_API_BASE_URL, accessToken: import.meta.env.VITE_DOCS_API_TOKEN }): ReviewApi {
  if (!environment.apiBaseUrl) throw new ApiConfigurationError("Review API is not configured. Set VITE_DOCS_API_BASE_URL before starting Review Studio.");
  const client = new ReviewApiClient({ baseUrl: environment.apiBaseUrl, accessToken: environment.accessToken, fetch: environment.fetch });
  return {
    ...client.system,
    ...client.workspaces,
    ...client.authoring,
    ...client.pipeline,
    ...client.review,
    ...client.delivery,
    ...client.templates,
    ...client.tools,
  };
}
