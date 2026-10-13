import { render } from "@testing-library/react";
import App from "../App";
import type { Capability, ReviewApi } from "../api/models";

const cap = (id: string, status: Capability["status"] = "available"): Capability => ({
  id, cli_command: id.replace(".", " "), route: status === "available" ? "POST /v2/x" : null, scopes: [], surface: "web+desktop", slice: "S2", status,
});
export const authoringCapabilityIds = ["asset.list", "asset.add", "asset.rm", "source.ingest", "document.classify", "context.status", "context.set", "context.show", "context.rm", "context.elicit", "context.ingest", "build-section", "review-section", "review-document", "stamp-section", "pack-context", "doc.revise", "revisions.list"];
export const catalogWithout = (...missing: string[]) => ({ groups: [{ id: "authoring", capabilities: authoringCapabilityIds.map(id => cap(id, missing.includes(id) ? "planned" : "available")) }] });

export const sections = [{ id: "intro", filename: "intro.md", body: "Intro body" }, { id: "summary", filename: "summary.md", body: "Summary body" }];

export function makeApi(overrides: Partial<ReviewApi> = {}): ReviewApi {
  return {
    listRuns: async () => [], listFindings: async () => [], listArtifacts: async () => [], listRevisions: async () => [],
    getCapabilities: async () => catalogWithout(),
    listWorkspaces: async () => [{ id: "ws-1", name: "Research", root: "C:/data" }],
    getCurrentDocument: async () => ({ current_document_id: "doc-1", document: { id: "doc-1", title: "Field notes", active: true } }),
    listAssets: async (documentId: string, kind?: string) => ({ document_id: documentId, kind: kind ?? "", items: [] }),
    getDocumentClassification: async (id: string) => ({ document_id: id, items: [] }),
    getDocumentContext: async (id: string) => ({ document_id: id, topics: [] }),
    listDocumentSections: async () => sections,
    updateDocumentSection: async () => ({}),
    ...overrides,
  } as unknown as ReviewApi;
}

export function openAuthoring(tab: string, api: ReviewApi) {
  window.location.hash = `#/authoring/${tab}`;
  return render(<App api={api} />);
}
