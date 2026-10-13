// Typed client for source, asset, classification and context routes (S2.1).

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
export interface ClassificationQueue { document_id: string; items: Array<Record<string, unknown>> }
export interface ContextRequests { document_id: string; path: string; markdown: string }
export interface ContextIngested { document_id: string; topics: string[] }
export interface ContextTopicContent { document_id: string; topic: string; content: string }
export interface ContextTopicRemoved { document_id: string; removed: string }

export interface AuthoringApi {
  listAssets(documentId: string, kind?: string): Promise<AssetList>;
  addAsset(documentId: string, input: { filename: string; contentBase64: string; name?: string }): Promise<AssetAdded>;
  removeAsset(documentId: string, name: string): Promise<AssetRemoved>;
  ingestSources(documentId: string, files?: SourceUploadInput[]): Promise<SourceIngestResult>;
  getClassificationQueue(documentId: string): Promise<ClassificationQueue>;
  confirmClassification(documentId: string, input: { relative_path: string; confirmed_role: ClassificationRole }): Promise<ClassificationQueue>;
  elicitContext(documentId: string, topic?: string): Promise<ContextRequests>;
  ingestContext(documentId: string): Promise<ContextIngested>;
  showContextTopic(documentId: string, topic: string): Promise<ContextTopicContent>;
  removeContextTopic(documentId: string, topic: string): Promise<ContextTopicRemoved>;
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
    getClassificationQueue: id => request(`${doc(id)}/classification`),
    confirmClassification: (id, input) => request(`${doc(id)}/classification`, json("POST", input)),
    elicitContext: (id, topic = "") => request(`${doc(id)}/context/requests`, json("POST", { topic })),
    ingestContext: id => request(`${doc(id)}/context/ingest`, json("POST", {})),
    showContextTopic: (id, topic) => request(`${doc(id)}/context/${encodeURIComponent(topic)}`),
    removeContextTopic: (id, topic) => request(`${doc(id)}/context/${encodeURIComponent(topic)}`, json("DELETE")),
  };
}
