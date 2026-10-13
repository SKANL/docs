// Typed client for the quality routes: run evidence, baseline promotion, inspect, diff, qa-docx, corrections (S4.1 contract).
import type { ScopedRequest } from "./authoring";

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

export interface QualityApi {
  getRunEvidence(runId: string): Promise<EvidenceBundle>;
  promoteBaseline(input: BaselinePromotionInput): Promise<BaselinePromotion>;
  inspectArtifact(artifactId: string): Promise<ArtifactInspect>;
  diffArtifacts(left: string, right: string): Promise<ArtifactDiff>;
  runQaDocx(documentId: string, options?: { strict?: boolean }): Promise<QaDocxResult>;
  applyCorrections(documentId: string): Promise<CorrectionsApplied>;
}

const post = (body: Record<string, unknown>): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const defined = (input: Record<string, unknown>) => Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
const isPng = (artifact: EvidenceArtifactRef) => artifact.media_type === "image/png" || artifact.kind.toLowerCase() === "png";

export function createQualityApi(request: ScopedRequest): QualityApi {
  const doc = (id: string) => `documents/${encodeURIComponent(id)}`;
  return {
    async getRunEvidence(runId) {
      const raw = await request<Omit<EvidenceBundle, "artifacts" | "previews"> & { artifacts?: Array<Record<string, string>>; previews?: PreviewAvailability }>(`runs/${encodeURIComponent(runId)}/evidence`);
      // The contract spells the digest `digest`; `sha256` is accepted so either spelling renders.
      const artifacts = (raw.artifacts ?? []).map(item => ({ id: item.id, kind: item.kind, digest: item.digest ?? item.sha256 ?? "", media_type: item.media_type ?? "" }));
      const pngs = artifacts.filter(isPng).map(item => item.id);
      return { ...raw, passport: raw.passport ?? {}, findings: raw.findings ?? [], artifacts, previews: raw.previews ?? { available: pngs.length > 0, artifact_ids: pngs } };
    },
    promoteBaseline: ({ runId, name, update }) => request("baselines/promotions", post(defined({ run_id: runId, name, update }))),
    inspectArtifact: id => request(`artifacts/${encodeURIComponent(id)}/inspect`),
    diffArtifacts: (left, right) => request("artifacts/diff", post({ left, right })),
    async runQaDocx(documentId, { strict } = {}) {
      const raw = await request<QaDocxResult & { reason?: string | null }>(`${doc(documentId)}/qa-docx`, post(defined({ strict })));
      const { reason, ...rest } = raw;
      return { ...rest, degraded_reason: rest.degraded_reason ?? reason ?? null };
    },
    applyCorrections: documentId => request(`${doc(documentId)}/corrections/apply`, post({})),
  };
}
