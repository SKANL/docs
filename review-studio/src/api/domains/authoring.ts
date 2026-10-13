// Typed client for source, asset, classification, context (S2.1) and section authoring (S2.2) routes.

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

export interface AuthoringApi {
  listAssets(documentId: string, kind?: string): Promise<AssetList>;
  addAsset(documentId: string, input: { filename: string; contentBase64: string; name?: string }): Promise<AssetAdded>;
  removeAsset(documentId: string, name: string): Promise<AssetRemoved>;
  ingestSources(documentId: string, files?: SourceUploadInput[]): Promise<SourceIngestResult>;
  listSources(documentId: string): Promise<SourceInventory>;
  getClassificationQueue(documentId: string): Promise<ClassificationQueue>;
  confirmClassification(documentId: string, input: { relative_path: string; confirmed_role: ClassificationRole }): Promise<ClassificationQueue>;
  elicitContext(documentId: string, topic?: string): Promise<ContextRequests>;
  ingestContext(documentId: string): Promise<ContextIngested>;
  showContextTopic(documentId: string, topic: string): Promise<ContextTopicContent>;
  removeContextTopic(documentId: string, topic: string): Promise<ContextTopicRemoved>;
  buildSection(documentId: string, sectionId: string): Promise<SectionBuilt>;
  packContext(documentId: string, target: string): Promise<ContextPacked>;
  reviewSection(documentId: string, sectionId: string, options?: { strict?: boolean }): Promise<ReviewResult>;
  reviewDocument(documentId: string, options?: { strict?: boolean; dimensions?: ReviewDimension[] }): Promise<ReviewResult>;
  stampSection(documentId: string, sectionId: string, input: { by: string; model?: string }): Promise<SectionStamped>;
  reviseDocument(documentId: string, input: RevisionInput): Promise<RevisionResult>;
}

/** Workspace-scoped request function supplied by the API client. */
export type ScopedRequest = <T>(path: string, init?: RequestInit) => Promise<T>;

const json = (method: string, body?: unknown): RequestInit => ({ method, ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
const doc = (id: string) => `documents/${encodeURIComponent(id)}`;

export function createAuthoringApi(request: ScopedRequest): AuthoringApi {
  return {
    listAssets: (id, kind) => request(`${doc(id)}/assets${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`),
    addAsset: (id, { filename, contentBase64, name }) => request(`${doc(id)}/assets`, json("POST", { filename, content_base64: contentBase64, ...(name ? { name } : {}) })),
    removeAsset: (id, name) => request(`${doc(id)}/assets/${encodeURIComponent(name)}`, json("DELETE")),
    ingestSources: (id, files = []) => request(`${doc(id)}/ingest`, json("POST", { files })),
    listSources: id => request(`${doc(id)}/sources`),
    getClassificationQueue: id => request(`${doc(id)}/classification`),
    confirmClassification: (id, input) => request(`${doc(id)}/classification`, json("POST", input)),
    elicitContext: (id, topic = "") => request(`${doc(id)}/context/requests`, json("POST", { topic })),
    ingestContext: id => request(`${doc(id)}/context/ingest`, json("POST", {})),
    showContextTopic: (id, topic) => request(`${doc(id)}/context/${encodeURIComponent(topic)}`),
    removeContextTopic: (id, topic) => request(`${doc(id)}/context/${encodeURIComponent(topic)}`, json("DELETE")),
    buildSection: (id, section) => request(`${doc(id)}/sections/${encodeURIComponent(section)}/build`, json("POST", {})),
    packContext: (id, target) => request(`${doc(id)}/context-pack`, json("POST", { target })),
    reviewSection: (id, section, options = {}) => request(`${doc(id)}/sections/${encodeURIComponent(section)}/review`, json("POST", options)),
    reviewDocument: (id, options = {}) => request(`${doc(id)}/review`, json("POST", options)),
    stampSection: (id, section, input) => request(`${doc(id)}/sections/${encodeURIComponent(section)}/stamp`, json("POST", input)),
    reviseDocument: (id, input) => request(`${doc(id)}/revisions`, json("POST", input)),
  };
}
