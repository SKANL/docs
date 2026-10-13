// Typed client for the delivery routes: package, publish, and the publication history (S5.1 contract).
// A release is not here: it is a pipeline run with policy "release" (see pipeline.runDocument).
import { defined, docPath, jsonInit, type Transport } from "../http";
import type { OutputFormat, RunPolicy } from "./pipeline";

export interface PackageInput { runId?: string; name?: string }
export interface PackageResult { document_id: string; run_id: string | null; source: string; destination: string; sha256: string; size_bytes: number }

export interface PublishInput { destination: string; format?: OutputFormat; policy?: RunPolicy }
export interface PublicationResult {
  id: string; document_id: string; format: string; policy: string; source: string; destination: string; manifest: string;
  artifact_sha256: string; manifest_sha256: string; provenance_run: string; attestation_sha256: string; identities: Record<string, unknown>; warnings: string[];
}

/** A history row reduced to what the UI shows. Policy and warnings are shown only when the server records them. */
export interface PublicationRecord {
  id: string; documentId?: string; destination: string; artifactSha256: string; runId?: string; publishedAt?: string;
  approver?: string; status?: string; policy?: string; warnings: string[];
}

const text = (value: unknown) => typeof value === "string" && value ? value : undefined;

export function toPublicationRecord(raw: Record<string, unknown>): PublicationRecord {
  return {
    id: String(raw.id ?? ""), documentId: text(raw.document_id), destination: text(raw.destination) ?? text(raw.artifact) ?? "",
    artifactSha256: text(raw.artifact_sha256) ?? "", runId: text(raw.run_id) ?? text(raw.provenance_run), publishedAt: text(raw.published_at),
    approver: text(raw.approver), status: text(raw.status), policy: text(raw.policy),
    warnings: Array.isArray(raw.warnings) ? raw.warnings.filter((item): item is string => typeof item === "string") : [],
  };
}

export interface DeliveryApi {
  packageDocument(documentId: string, input?: PackageInput): Promise<PackageResult>;
  publishDocument(documentId: string, input: PublishInput): Promise<PublicationResult>;
  listPublicationHistory(): Promise<PublicationRecord[]>;
}

export function createDeliveryApi(t: Transport): DeliveryApi {
  const request = t.scoped;
  return {
    packageDocument: (id, { runId, name } = {}) => request(`${docPath(id)}/package`, jsonInit("POST", defined({ run_id: runId, name }))),
    publishDocument: (id, { destination, format, policy }) => request(`${docPath(id)}/publications`, jsonInit("POST", defined({ destination, format, policy }))),
    async listPublicationHistory() {
      const raw = await request<{ items?: Array<Record<string, unknown>> }>("publications");
      return (raw.items ?? []).map(toPublicationRecord);
    },
  };
}
