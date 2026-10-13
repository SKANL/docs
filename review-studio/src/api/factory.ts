import { ApiConfigurationError, ReviewApiClient } from "./client";
import type { ReviewApi } from "./models";

export type ReviewApiEnvironment = {
  apiBaseUrl?: string;
  accessToken?: string;
  fetch?: typeof globalThis.fetch;
};

function remoteApi(client: ReviewApiClient): ReviewApi {
  return {
    ...client.authoring,
    ...client.pipeline,
    ...client.quality,
    ...client.delivery,
    ...client.templates,
    ...client.tools,
    health: () => client.health(),
    getCapabilities: () => client.getCapabilities(),
    listRuns: () => client.listRuns(),
    getRun: id => client.getRun(id),
    listDocuments: workspaceId => client.listDocuments(workspaceId),
    getDocument: id => client.getDocument(id),
    listDocumentRuns: id => client.listDocumentRuns(id),
    listFindings: () => client.listFindings(),
    listRunFindings: id => client.listRunFindings(id),
    listArtifacts: () => client.listArtifacts(),
    listRunArtifacts: id => client.listRunArtifacts(id),
    getArtifact: id => client.getArtifact(id),
    listArtifactPreviews: id => client.listArtifactPreviews(id),
    getPassport: runId => client.getPassport(runId),
    getGraph: () => client.getGraph(),
    getGraphQuery: (query, id) => client.getGraphQuery(query, id),
    listTemplates: () => client.listTemplates(),
    listBaselines: () => client.listBaselines(),
    getBaseline: id => client.getBaseline(id),
    listRevisions: () => client.listRevisions(),
    getRevision: id => client.getRevision(id),
    listPublications: () => client.listPublications(),
    listPlugins: () => client.listPlugins(),
    getPlugin: id => client.getPlugin(id),
    listWorkspaces: () => client.listWorkspaces(),
    createWorkspace: input => client.createWorkspace(input), renameWorkspace: (id, name) => client.renameWorkspace(id, name), deleteWorkspace: id => client.deleteWorkspace(id),
    getWorkspaceStatus: id => client.getWorkspaceStatus(id), migrateWorkspace: (id, input) => client.migrateWorkspace(id, input),
    getCurrentDocument: workspaceId => client.getCurrentDocument(workspaceId), useDocument: (id, workspaceId) => client.useDocument(id, workspaceId),
    renameDocument: (id, newId, workspaceId) => client.renameDocument(id, newId, workspaceId), deleteDocument: (id, workspaceId) => client.deleteDocument(id, workspaceId),
    getDocumentStatus: (documentId, workspaceId) => client.getDocumentStatus(documentId, workspaceId),
    getDocumentContext: documentId => client.getDocumentContext(documentId),
    setDocumentContext: (documentId, input) => client.setDocumentContext(documentId, input),
    listDocumentSections: documentId => client.listDocumentSections(documentId),
    getDocumentSection: (documentId, sectionId) => client.getDocumentSection(documentId, sectionId),
    updateDocumentSection: (documentId, sectionId, body, request) => client.updateDocumentSection(documentId, sectionId, body, request),
    createDocument: input => client.createDocument(input),
    createRun: input => client.createRun(input), getDocumentClassification: id => client.getDocumentClassification(id), confirmDocumentClassification: (id,input) => client.confirmDocumentClassification(id,input), reviseDocument: (documentId, input) => client.reviseDocument(documentId, input), documentAction: (documentId, action, workspaceId, format) => client.documentAction(documentId, action, workspaceId, format), cancelRun: id => client.cancelRun(id), retryRun: id => client.retryRun(id),
    selectWorkspace: id => client.selectWorkspace(id),
    importDocument: (file, workspace, options) => client.importDocument(file, workspace, options),
    artifactPreviewUrl: (runId, artifactId) => client.artifactPreviewUrl(runId, artifactId),
    streamProgress: (runId, onEvent, signal) => client.streamProgress(runId, onEvent, signal),
  };
}

export function createReviewApi(environment: ReviewApiEnvironment = { apiBaseUrl: import.meta.env.VITE_DOCS_API_BASE_URL, accessToken: import.meta.env.VITE_DOCS_API_TOKEN }): ReviewApi {
  if (!environment.apiBaseUrl) throw new ApiConfigurationError("Review API is not configured. Set VITE_DOCS_API_BASE_URL before starting Review Studio.");
  return remoteApi(new ReviewApiClient({ baseUrl: environment.apiBaseUrl, accessToken: environment.accessToken, fetch: environment.fetch }));
}
