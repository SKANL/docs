import { ApiConfigurationError, ReviewApiClient } from "./client";
import { mockApi } from "./mockApi";
import type { ReviewApi } from "./models";

export type ReviewApiEnvironment = {
  apiBaseUrl?: string;
  mockEnabled?: boolean;
  isDevelopment?: boolean;
};

function remoteApi(client: ReviewApiClient): ReviewApi {
  return {
    listRuns: () => client.listRuns().then(page => page.items),
    listFindings: () => client.listFindings().then(page => page.items),
    listArtifacts: () => client.listArtifacts().then(page => page.items),
    getPassport: runId => client.getPassport(runId),
    getGraph: () => client.getGraph(),
    getGraphQuery: (query, id) => client.getGraphQuery(query, id),
    listTemplates: () => client.listTemplates().then(page => page.items),
    listBaselines: () => client.listBaselines().then(page => page.items),
    listRevisions: () => client.listRevisions().then(page => page.items),
    listPublications: () => client.listPublications().then(page => page.items),
    streamProgress: (runId, onEvent, signal) => client.streamProgress(runId, onEvent, signal),
  };
}

export function createReviewApi(environment: ReviewApiEnvironment = {
  apiBaseUrl: import.meta.env.VITE_DOCS_API_BASE_URL,
  mockEnabled: import.meta.env.VITE_REVIEW_STUDIO_MOCK_API === "true",
  isDevelopment: import.meta.env.DEV || import.meta.env.MODE === "test",
}): ReviewApi {
  if (environment.mockEnabled) {
    if (!environment.isDevelopment) throw new ApiConfigurationError("The mock API is available only in development or test mode.");
    return mockApi;
  }
  if (!environment.apiBaseUrl) throw new ApiConfigurationError("Review API is not configured. Set VITE_DOCS_API_BASE_URL before starting Review Studio.");
  return remoteApi(new ReviewApiClient({ baseUrl: environment.apiBaseUrl }));
}
