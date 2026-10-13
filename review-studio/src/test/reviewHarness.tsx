import { render } from "@testing-library/react";
import App from "../App";
import type { Capability, ReviewApi } from "../api/models";
import type { EvidenceBundle } from "../api/domains/review";
import { makeApi } from "./authoringHarness";

const cap = (id: string, status: Capability["status"] = "available"): Capability => ({
  id, cli_command: id.replace(".", " "), route: status === "available" ? "POST /v2/x" : null, scopes: [], surface: "web+desktop", slice: "S4", status,
});
export const reviewCapabilityIds = ["document.evidence", "document.passport", "document.baseline", "document.inspect", "document.diff", "qa-docx", "apply-corrections"];
export const reviewCatalog = (...missing: string[]) => ({ groups: [{ id: "review", capabilities: reviewCapabilityIds.map(id => cap(id, missing.includes(id) ? "planned" : "available")) }] });

export const finding = (over: Record<string, unknown> = {}) => ({ id: "f-1", runId: "run-1", title: "Heading is missing", severity: "high" as const, status: "failed" as const, location: "section intro", summary: "Intro has no heading", owner: "-", updated: "-", ...over });
export const artifact = (over: Record<string, unknown> = {}) => ({ id: "a-1", name: "report.docx", runId: "run-1", kind: "DOCX" as const, size: "10 bytes", status: "passed" as const, checksum: "abc123", ...over });
export const bundle = (over: Partial<EvidenceBundle> = {}): EvidenceBundle => ({
  run_id: "run-1", evidence_sha256: "f".repeat(64),
  passport: { run_id: "run-1", entries: [{ stage: "pipeline_stage", name: "build-html", receipt: { outcome: "passed", artifacts: ["a"], warnings: [], errors: [] } }, { stage: "worker", retry_of: "run-0", attempt: 2 }] },
  artifacts: [{ id: "a-1", kind: "docx", digest: "d".repeat(64), media_type: "application/vnd" }],
  findings: [{ id: "f-1", severity: "high", message: "Heading is missing" }],
  previews: { available: true, artifact_ids: ["p-1"] }, ...over,
});
export const inspected = { artifact_id: "a-1", path: "output/report.docx", media_type: "application/vnd", sha256: "9".repeat(64), size_bytes: 2048 };

export function makeReviewApi(overrides: Partial<ReviewApi> = {}): ReviewApi {
  return makeApi({
    getCapabilities: async () => reviewCatalog(),
    listFindings: async () => [finding()],
    listArtifacts: async () => [artifact()],
    listRuns: async () => [{ id: "run-1", document: "doc-1", template: "-", startedAt: "2026-01-01T00:00:00Z", duration: "-", status: "passed", findings: 1, artifactCount: 1 }],
    listBaselines: async () => [],
    getRunEvidence: async () => bundle(),
    artifactPreviewUrl: (runId: string, id: string) => `https://review.test/v2/runs/${runId}/previews/${id}`,
    listArtifactPreviews: async () => [],
    getGraph: async () => ({ nodes: [], edges: [] }),
    getGraphQuery: async () => ({ items: [] }),
    ...overrides,
  } as Partial<ReviewApi>);
}

export function openReview(path: string, api: ReviewApi) {
  window.location.hash = `#${path}`;
  return render(<App api={api} />);
}
