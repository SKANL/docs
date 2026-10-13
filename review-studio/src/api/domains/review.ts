// Typed client for the review routes: findings, artifacts, run evidence, baselines, graph, inspect, diff, qa-docx, corrections (S4.1 contract).
import { ApiConfigurationError } from "../errors";
import { defined, docPath, jsonInit, listPage, type ListParams, type Transport } from "../http";

export type Status = "passed" | "warnings" | "failed" | "unverified";

/** A finding exactly as the server sends it; field names vary, so the UI reads it tolerantly (see `toFindingRow`). */
export type RawFinding = Record<string, unknown>;
export type Artifact = { id: string; name: string; runId?: string; kind: "DOCX" | "PDF" | "HTML" | "PNG"; size: string; status: Status; pages?: number; checksum: string };
export type Baseline = { id: string; name: string; scope: string; created: string; status: Status; delta: string };
export type GraphNode = { id: string; label: string; type: "claim" | "source" | "artifact" | "section"; confidence: number; x: number; y: number };
export type GraphEdge = { from: string; to: string; relation: string };
export type GraphQuery = "claims_without_evidence" | "findings_affected_by_revision" | "artifacts_derived_from_input" | "unused_references" | "unmet_requirements";
export type GraphQueryItem = { id: string; kind: string; label: string; confidence?: number; attributes?: Record<string, unknown> };
export type GraphQueryResult = { items: GraphQueryItem[]; graphUnavailable?: boolean; warnings?: string[]; context?: Record<string, unknown> };

export interface EvidenceArtifactRef { id: string; kind: string; digest: string; media_type: string }
export interface PreviewAvailability { available: boolean; artifact_ids: string[] }
export interface EvidenceBundle {
  run_id: string; evidence_sha256: string; passport: Record<string, unknown>;
  artifacts: EvidenceArtifactRef[]; findings: Array<Record<string, unknown>>; previews: PreviewAvailability;
}
export interface BaselinePromotionInput { runId: string; name?: string; update?: boolean }
export interface BaselinePromotion { run_id: string; name: string; destination: string; replaced: boolean; pages: Array<{ name: string; sha256: string }> }
/** Paths are workspace-relative. */
export interface ArtifactReport { path: string; media_type: string; sha256: string; size_bytes: number }
export interface ArtifactInspect extends ArtifactReport { artifact_id: string }
export interface ArtifactDiff { same: boolean; left: ArtifactReport; right: ArtifactReport; text_diff: string[] }
export interface QaDocxResult {
  document_id: string; docx: string; strict: boolean; passed: boolean; message: string | null;
  degraded: boolean; degraded_reason: string | null; report: string | null;
}
export interface CorrectionsApplied { document_id: string; applied: number }

export interface ReviewDomainApi {
  listFindings(params?: ListParams): Promise<RawFinding[]>;
  listArtifacts(params?: ListParams): Promise<Artifact[]>;
  listArtifactPreviews(id: string): Promise<Record<string, unknown>[]>;
  artifactPreviewUrl(runId: string, artifactId: string): string;
  getGraph(): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }>;
  getGraphQuery(query: GraphQuery, id?: string): Promise<GraphQueryResult>;
  listBaselines(params?: ListParams): Promise<Baseline[]>;
  getBaseline(id: string): Promise<Record<string, unknown>>;
  getRunEvidence(runId: string): Promise<EvidenceBundle>;
  promoteBaseline(input: BaselinePromotionInput): Promise<BaselinePromotion>;
  inspectArtifact(artifactId: string): Promise<ArtifactInspect>;
  diffArtifacts(left: string, right: string): Promise<ArtifactDiff>;
  runQaDocx(documentId: string, options?: { strict?: boolean }): Promise<QaDocxResult>;
  applyCorrections(documentId: string): Promise<CorrectionsApplied>;
}

const isPng = (artifact: EvidenceArtifactRef) => artifact.media_type === "image/png" || artifact.kind.toLowerCase() === "png";

type RawGraphNode = { id?: unknown; kind?: unknown; label?: unknown; confidence?: unknown; attributes?: unknown; x?: unknown; y?: unknown };
type RawGraphEdge = { source?: unknown; target?: unknown; relation?: unknown; from?: unknown; to?: unknown };

const graphType = (kind: string): GraphNode["type"] => {
  if (kind === "claim" || kind === "artifact" || kind === "section" || kind === "source") return kind;
  return kind === "evidence" || kind === "input" || kind === "reference" ? "source" : "claim";
};

const confidenceScore = (value: unknown): number => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (value && typeof value === "object" && typeof (value as { score?: unknown }).score === "number") return (value as { score: number }).score;
  return 0;
};

function normalizeArtifactKind(value: unknown): Artifact["kind"] {
  const kind = typeof value === "string" ? value.toUpperCase() : "";
  if (kind.includes("PDF")) return "PDF";
  if (kind.includes("HTML")) return "HTML";
  if (kind.includes("PNG") || kind.includes("PREVIEW")) return "PNG";
  return "DOCX";
}

function toArtifact(raw: Record<string, unknown>): Artifact {
  return {
    id: typeof raw.id === "string" ? raw.id : "artifact",
    name: typeof raw.name === "string" ? raw.name : typeof raw.id === "string" ? raw.id : "Unnamed artifact",
    runId: typeof raw.run_id === "string" ? raw.run_id : undefined,
    kind: normalizeArtifactKind(raw.kind),
    size: typeof raw.size === "string" ? raw.size : typeof raw.size === "number" ? `${raw.size} bytes` : "Size unavailable",
    status: raw.status === "failed" || raw.status === "warnings" || raw.status === "passed" ? raw.status : "unverified",
    pages: typeof raw.pages === "number" ? raw.pages : undefined,
    checksum: typeof raw.checksum === "string" ? raw.checksum : typeof raw.digest === "string" ? raw.digest : "Hash unavailable",
  };
}

function normalizeGraph(payload: unknown): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const value = payload && typeof payload === "object" ? payload as { nodes?: unknown; edges?: unknown } : {};
  const rawNodes = Array.isArray(value.nodes) ? value.nodes as RawGraphNode[] : [];
  const nodes = rawNodes.flatMap((node, index) => {
    if (typeof node.id !== "string") return [];
    const angle = rawNodes.length ? (index / rawNodes.length) * Math.PI * 2 : 0;
    return [{ id: node.id, label: typeof node.label === "string" ? node.label : node.id, type: graphType(typeof node.kind === "string" ? node.kind : "entity"), confidence: confidenceScore(node.confidence), x: typeof node.x === "number" ? node.x : 50 + Math.cos(angle) * 32, y: typeof node.y === "number" ? node.y : 50 + Math.sin(angle) * 32 }];
  });
  const edges = (Array.isArray(value.edges) ? value.edges as RawGraphEdge[] : []).flatMap(edge => {
    const from = typeof edge.source === "string" ? edge.source : edge.from;
    const to = typeof edge.target === "string" ? edge.target : edge.to;
    return typeof from === "string" && typeof to === "string" ? [{ from, to, relation: typeof edge.relation === "string" ? edge.relation : "related" }] : [];
  });
  return { nodes, edges };
}

function normalizeGraphQuery(payload: unknown): GraphQueryResult {
  const value = payload && typeof payload === "object" ? payload as { items?: unknown; graph_unavailable?: unknown; warnings?: unknown; context?: unknown } : {};
  const items = (Array.isArray(value.items) ? value.items : []).flatMap((item): GraphQueryItem[] => {
    if (!item || typeof item !== "object") return [];
    const candidate = item as Record<string, unknown>;
    if (typeof candidate.id !== "string") return [];
    const attributes = candidate.attributes && typeof candidate.attributes === "object" ? candidate.attributes as Record<string, unknown> : undefined;
    return [{ id: candidate.id, kind: typeof candidate.kind === "string" ? candidate.kind : "entity", label: typeof candidate.label === "string" ? candidate.label : candidate.id, confidence: confidenceScore(candidate.confidence), attributes }];
  });
  return { items, graphUnavailable: value.graph_unavailable === true, warnings: Array.isArray(value.warnings) ? value.warnings.filter((warning): warning is string => typeof warning === "string") : undefined, context: value.context && typeof value.context === "object" ? value.context as Record<string, unknown> : undefined };
}

export function createReviewDomainApi(t: Transport): ReviewDomainApi {
  const request = t.scoped;
  return {
    listFindings: async params => (await listPage<RawFinding>(request, "findings", params)).items,
    listArtifacts: async params => (await listPage<Record<string, unknown>>(request, "artifacts", params)).items.map(toArtifact),
    listArtifactPreviews: async id => (await listPage<Record<string, unknown>>(request, `artifacts/${encodeURIComponent(id)}/previews`)).items,
    artifactPreviewUrl(runId, artifactId) {
      if (!t.session.selected) throw new ApiConfigurationError("Select a workspace before requesting an artifact preview.");
      return t.previewUrl(`runs/${encodeURIComponent(runId)}/previews/${encodeURIComponent(artifactId)}?workspace_id=${encodeURIComponent(t.session.selected)}`);
    },
    getGraph: async () => normalizeGraph(await request<unknown>("graph")),
    async getGraphQuery(query, id) {
      const params = new URLSearchParams({ query });
      if (id) params.set("id", id);
      return normalizeGraphQuery(await request<unknown>(`graph?${params}`));
    },
    listBaselines: async params => (await listPage<Baseline>(request, "baselines", params)).items,
    getBaseline: id => request(`baselines/${encodeURIComponent(id)}`),
    async getRunEvidence(runId) {
      const raw = await request<Omit<EvidenceBundle, "artifacts" | "previews"> & { artifacts?: Array<Record<string, string>>; previews?: PreviewAvailability }>(`runs/${encodeURIComponent(runId)}/evidence`);
      // The contract spells the digest `digest`; `sha256` is accepted so either spelling renders.
      const artifacts = (raw.artifacts ?? []).map(item => ({ id: item.id, kind: item.kind, digest: item.digest ?? item.sha256 ?? "", media_type: item.media_type ?? "" }));
      const pngs = artifacts.filter(isPng).map(item => item.id);
      return { ...raw, passport: raw.passport ?? {}, findings: raw.findings ?? [], artifacts, previews: raw.previews ?? { available: pngs.length > 0, artifact_ids: pngs } };
    },
    promoteBaseline: ({ runId, name, update }) => request("baselines/promotions", jsonInit("POST", defined({ run_id: runId, name, update }))),
    inspectArtifact: id => request(`artifacts/${encodeURIComponent(id)}/inspect`),
    diffArtifacts: (left, right) => request("artifacts/diff", jsonInit("POST", { left, right })),
    async runQaDocx(documentId, { strict } = {}) {
      const raw = await request<QaDocxResult & { reason?: string | null }>(`${docPath(documentId)}/qa-docx`, jsonInit("POST", defined({ strict })));
      const { reason, ...rest } = raw;
      return { ...rest, degraded_reason: rest.degraded_reason ?? reason ?? null };
    },
    applyCorrections: documentId => request(`${docPath(documentId)}/corrections/apply`, jsonInit("POST", {})),
  };
}
