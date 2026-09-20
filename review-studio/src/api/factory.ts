import { ApiConfigurationError, ReviewApiClient } from "./client";
import type { ReviewApi } from "./models";

export type ReviewApiEnvironment = {
  apiBaseUrl?: string;
  fetch?: typeof globalThis.fetch;
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
    listWorkspaces: () => client.listWorkspaces().then(page => page.items),
    createWorkspace: input => client.createWorkspace(input),
    createDocument: input => client.createDocument(input),
    createRun: input => client.createRun(input), cancelRun: id => client.cancelRun(id), retryRun: id => client.retryRun(id),
    selectWorkspace: id => client.selectWorkspace(id),
    importDocument: (file, workspace) => client.importDocument(file, workspace),
    streamProgress: (runId, onEvent, signal) => client.streamProgress(runId, onEvent, signal),
  };
}

export function createReviewApi(environment: ReviewApiEnvironment = { apiBaseUrl: import.meta.env.VITE_DOCS_API_BASE_URL }): ReviewApi {
  if (!environment.apiBaseUrl) throw new ApiConfigurationError("Review API is not configured. Set VITE_DOCS_API_BASE_URL before starting Review Studio.");
  return remoteApi(new ReviewApiClient({ baseUrl: environment.apiBaseUrl, fetch: environment.fetch }));
}
