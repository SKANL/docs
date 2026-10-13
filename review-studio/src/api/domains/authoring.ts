// Typed client for source, asset, classification, context (S2.1), section authoring (S2.2) and revision routes.
import { docPath, jsonInit, listPage, type ListParams, type Transport } from "../http";
import type { Status } from "./review";

export type ClassificationRole = "evidence" | "example" | "normative";

export interface AssetList { document_id: string; kind: string; items: Array<{ name: string }> }
export interface AssetAdded { document_id: string; name: string; path: string }
export interface AssetRemoved { document_id: string; removed: string }
export interface SourceUploadInput { filename: string; content_base64: string }
export interface IngestStage { name: string; succeeded: boolean; status: string | null; processed: number | null; errors: string[]; warnings: string[]; files: Array<Record<string, unknown>> }
export interface SourceIngestResult {
  document_id: string;
  succeeded: boolean;
  artifacts: string[];
  uploaded: Array<{ filename: string; sha256: string; size: number; deduplicated: boolean }>;
  stages: IngestStage[];
}
/** A source file the server holds for the document: raw in the inbox, or already converted by ingest. */
export interface SourceInventory { document_id: string; items: Array<{ name: string; path: string; state: "inbox" | "ingested" }> }
export interface ClassificationQueue { document_id: string; items: Array<Record<string, unknown>> }
export type DocumentContextTopic = { id: string; title: string; required: boolean; exists: boolean; missing: boolean; fields: Array<{ key: string; label: string; required?: boolean }> };
export interface ContextStatus { document_id: string; topics: DocumentContextTopic[] }
export interface ContextRequests { document_id: string; path: string; markdown: string }
export interface ContextIngested { document_id: string; topics: string[] }
export interface ContextTopicContent { document_id: string; topic: string; content: string }
export interface ContextTopicRemoved { document_id: string; removed: string }

export type ReviewDimension = "editorial" | "evidence" | "consistency" | "structural" | "accessibility" | "visual" | "reproducibility";
export interface ReviewFinding {
  severity: string; message: string; code: string; dimension: string;
  evidence?: string | null; resolution_condition?: string | null; section?: string | null;
  file?: string | null; page?: number | null; stage_originator?: string | null;
}
/** Paths are relative to the document root. */
export interface SectionBuilt { document_id: string; section_id: string; path: string; proposal: boolean }
export interface ContextPacked { document_id: string; target: string; paths: string[] }
export interface ReviewResult { document_id: string; section_id: string | null; passed: boolean; findings: ReviewFinding[] }
export interface SectionStamped { document_id: string; section_id: string; path: string; authored_by: string; model: string; stamped_at: string }
export interface RevisionInput { target_id: string; new_body?: string; new_value?: string; request?: string; field?: string; strict?: boolean }
export interface RevisionResult { target_id: string; diff: string; summary: string; changed_sections: string[]; diff_path: string }

export type DocumentSection = { id: string; filename: string; body: string };
export type Revision = { id: string; message: string; author: string; date: string; status: Status; files: number };

export interface AuthoringApi {
  listAssets(documentId: string, kind?: string): Promise<AssetList>;
  addAsset(documentId: string, input: { filename: string; contentBase64: string; name?: string }): Promise<AssetAdded>;
  removeAsset(documentId: string, name: string): Promise<AssetRemoved>;
  ingestSources(documentId: string, files?: SourceUploadInput[]): Promise<SourceIngestResult>;
  listSources(documentId: string): Promise<SourceInventory>;
  getClassificationQueue(documentId: string): Promise<ClassificationQueue>;
  confirmClassification(documentId: string, input: { relative_path: string; confirmed_role: ClassificationRole }): Promise<ClassificationQueue>;
  getDocumentContext(documentId: string): Promise<ContextStatus>;
  setDocumentContext(documentId: string, input: { topic: string; field?: string; value: string }): Promise<Record<string, unknown>>;
  elicitContext(documentId: string, topic?: string): Promise<ContextRequests>;
  ingestContext(documentId: string): Promise<ContextIngested>;
  showContextTopic(documentId: string, topic: string): Promise<ContextTopicContent>;
  removeContextTopic(documentId: string, topic: string): Promise<ContextTopicRemoved>;
  listDocumentSections(documentId: string): Promise<DocumentSection[]>;
  updateDocumentSection(documentId: string, sectionId: string, body: string, request?: string): Promise<Record<string, unknown>>;
  buildSection(documentId: string, sectionId: string): Promise<SectionBuilt>;
  packContext(documentId: string, target: string): Promise<ContextPacked>;
  reviewSection(documentId: string, sectionId: string, options?: { strict?: boolean }): Promise<ReviewResult>;
  reviewDocument(documentId: string, options?: { strict?: boolean; dimensions?: ReviewDimension[] }): Promise<ReviewResult>;
  stampSection(documentId: string, sectionId: string, input: { by: string; model?: string }): Promise<SectionStamped>;
  reviseDocument(documentId: string, input: RevisionInput): Promise<RevisionResult>;
  listRevisions(params?: ListParams): Promise<Revision[]>;
  getRevision(id: string): Promise<Record<string, unknown>>;
}

const sectionPath = (documentId: string, sectionId: string) => `${docPath(documentId)}/sections/${encodeURIComponent(sectionId)}`;

export function createAuthoringApi(t: Transport): AuthoringApi {
  const request = t.scoped;
  return {
    listAssets: (id, kind) => request(`${docPath(id)}/assets${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`),
    addAsset: (id, { filename, contentBase64, name }) => request(`${docPath(id)}/assets`, jsonInit("POST", { filename, content_base64: contentBase64, ...(name ? { name } : {}) })),
    removeAsset: (id, name) => request(`${docPath(id)}/assets/${encodeURIComponent(name)}`, jsonInit("DELETE")),
    ingestSources: (id, files = []) => request(`${docPath(id)}/ingest`, jsonInit("POST", { files })),
    listSources: id => request(`${docPath(id)}/sources`),
    getClassificationQueue: id => request(`${docPath(id)}/classification`),
    confirmClassification: (id, input) => request(`${docPath(id)}/classification`, jsonInit("POST", input)),
    getDocumentContext: id => request(`${docPath(id)}/context`),
    setDocumentContext: (id, input) => request(`${docPath(id)}/context`, jsonInit("POST", input)),
    elicitContext: (id, topic = "") => request(`${docPath(id)}/context/requests`, jsonInit("POST", { topic })),
    ingestContext: id => request(`${docPath(id)}/context/ingest`, jsonInit("POST", {})),
    showContextTopic: (id, topic) => request(`${docPath(id)}/context/${encodeURIComponent(topic)}`),
    removeContextTopic: (id, topic) => request(`${docPath(id)}/context/${encodeURIComponent(topic)}`, jsonInit("DELETE")),
    listDocumentSections: async id => (await request<{ items: DocumentSection[] }>(`${docPath(id)}/sections`)).items,
    updateDocumentSection: (id, sectionId, body, requestText = "Review Studio section edit") => request(sectionPath(id, sectionId), jsonInit("PUT", { body, request: requestText })),
    buildSection: (id, section) => request(`${sectionPath(id, section)}/build`, jsonInit("POST", {})),
    packContext: (id, target) => request(`${docPath(id)}/context-pack`, jsonInit("POST", { target })),
    reviewSection: (id, section, options = {}) => request(`${sectionPath(id, section)}/review`, jsonInit("POST", options)),
    reviewDocument: (id, options = {}) => request(`${docPath(id)}/review`, jsonInit("POST", options)),
    stampSection: (id, section, input) => request(`${sectionPath(id, section)}/stamp`, jsonInit("POST", input)),
    reviseDocument: (id, input) => request(`${docPath(id)}/revisions`, jsonInit("POST", input)),
    listRevisions: async params => (await listPage<Revision>(request, "revisions", params)).items,
    getRevision: id => request(`revisions/${encodeURIComponent(id)}`),
  };
}
