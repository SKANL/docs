import type { Capability, ReviewApi } from "../api/models";
import type { PackageResult, PublicationRecord, PublicationResult } from "../api/domains/delivery";
import { pipelineCapabilityIds, streamingApi } from "./pipelineHarness";

const cap = (id: string, status: Capability["status"] = "available"): Capability => ({
  id, cli_command: id.replace(".", " "), route: status === "available" ? "POST /v2/x" : null, scopes: [], surface: "web+desktop", slice: "S5", status,
});
const deliveryCapabilityIds = ["document.package", "document.publish", "document.release", "publications.list"];
export const deliveryCatalog = (...missing: string[]) => ({ groups: [{ id: "delivery", capabilities: [...pipelineCapabilityIds, ...deliveryCapabilityIds].map(id => cap(id, missing.includes(id) ? "planned" : "available")) }] });

export const packaged: PackageResult = { document_id: "doc-1", run_id: null, source: "documents/doc-1/output/current", destination: "artifacts/packages/doc-1-current.zip", sha256: "a".repeat(64), size_bytes: 2048 };
export const published: PublicationResult = {
  id: "pub-1", document_id: "doc-1", format: "html", policy: "release", source: "documents/doc-1/output/current/doc-1.html", destination: "documents/doc-1/output/release/final.html",
  manifest: "documents/doc-1/output/release/final.html.manifest.json", artifact_sha256: "b".repeat(64), manifest_sha256: "c".repeat(64), provenance_run: "run-7", attestation_sha256: "d".repeat(64), identities: {}, warnings: ["font substituted"],
};
export const record = (over: Partial<PublicationRecord> = {}): PublicationRecord => ({
  id: "pub-0", documentId: "doc-1", destination: "documents/doc-1/output/release/old.html", artifactSha256: "e".repeat(64), runId: "run-3", publishedAt: "2026-01-01T00:00:00Z", approver: "local", status: "passed", warnings: [], ...over,
});

export function deliveryApi(overrides: Partial<ReviewApi> = {}) {
  return streamingApi({
    getCapabilities: async () => deliveryCatalog(),
    packageDocument: async () => packaged,
    publishDocument: async () => published,
    listPublicationHistory: async () => [],
    ...overrides,
  } as Partial<ReviewApi>);
}
